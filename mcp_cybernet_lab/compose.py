"""Compile a testbed into a build folder: Dockerfiles, docker-compose.yml, seeded data, manifest.

build/<testbed>/
  docker-compose.yml
  context/                 runtime files copied into every image (agent, gateway, proxies, servers)
  dockerfiles/<service>.Dockerfile
  data/<server>/           what each server sees at its mount point (canaries planted)
  data.pristine/           copy of data/, restored by `mcl reset`
  policy/current.json      the guard policy the gateway loads (when a gateway is configured)
  canaries.json            ground truth: every planted canary and where it lives
  manifest.json            what was built, from which file, with which seed

Run outputs go to runs/<testbed>/ (outside build/, so a rebuild never deletes results).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import __version__
from .guards import default_policy
from .loader import Loaded, TestbedError, check_buildable
from .schema import Client, Server, Service, Testbed
from .seeding import canary_file_text, make_canaries, stream

REPO = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent
RUNTIME = REPO / "images" / "runtime"
CONTAINER_MODULES = ["probe.py", "mcpclient.py", "agent.py", "httpproxy.py", "authproxy.py",
                     "gateway.py", "guards.py", "sink.py"]
HTTP_PORT = 8080
INNER_PORT = 8081  # where a server listens when an auth proxy sits in front of it
MCP_PROXY = "mcp-proxy==0.13.0"
BASE_IMAGE = "node:22-bookworm-slim"
UV_IMAGE = "ghcr.io/astral-sh/uv:0.9.5"
GATEWAY_NET = "net-gateway"


def network_name(domain: str) -> str:
    return f"net-{domain}"


def domain_token(tb: Testbed, domain: str) -> str:
    """Per-domain bearer token, derived from the seed (testbed secret, not a real credential)."""
    return "mcl_" + "".join(stream(tb.seed, "token", domain).choice("0123456789abcdef") for _ in range(32))


def needs_token(tb: Testbed, s: Server) -> bool:
    return s.transport == "http" and any(d.id == s.domain and d.auth == "token" for d in tb.domains)


def dockerfile(installs: list[Server], cmd: list[str]) -> str:
    lines = [
        f"FROM {BASE_IMAGE}",
        "RUN apt-get update && apt-get install -y --no-install-recommends \\",
        "      python3 python3-venv git iproute2 ca-certificates \\",
        " && rm -rf /var/lib/apt/lists/*",
        f"COPY --from={UV_IMAGE} /uv /uvx /usr/local/bin/",
        "ENV UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin UV_PYTHON_PREFERENCE=only-system",
        f"RUN uv tool install {MCP_PROXY}",
        "COPY install_server.py entrypoint.sh /opt/mcl/",
        "RUN chmod +x /opt/mcl/*.sh /opt/mcl/*.py",
    ]
    for s in installs:
        if s.runtime == "local":  # custom server: its source is copied into the build context
            lines.append(f"COPY servers/{s.id} /opt/mcp-src/{s.id}")
            source = f"/opt/mcp-src/{s.id}"
        else:
            source = s.package
        lines.append(f"RUN python3 /opt/mcl/install_server.py {s.runtime} {source} {s.version or '-'} {s.id}"
                     + "".join(f" '{w}'" for w in s.with_packages))
    # The lab's own Python files change most often: copy them last, to keep the layers above cached.
    lines.append("COPY " + " ".join(CONTAINER_MODULES) + " /opt/mcl/")
    lines.append('ENTRYPOINT ["/opt/mcl/entrypoint.sh"]')
    lines.append(f"CMD {json.dumps(cmd)}")
    return "\n".join(lines) + "\n"


def netem_env(s: Server) -> dict[str, str]:
    n = s.network
    if n.is_default:
        return {}
    env = {}
    if n.delay_ms or n.jitter_ms:
        env["MCL_DELAY_MS"] = str(n.delay_ms)
        env["MCL_JITTER_MS"] = str(n.jitter_ms)
    if n.loss:
        env["MCL_LOSS_PCT"] = f"{n.loss * 100:g}"
    return env


def llm_env(tb: Testbed) -> dict[str, str]:
    env = {"MCL_LLM": json.dumps(tb.llm.model_dump())}
    if tb.llm.api_key_env:
        env[tb.llm.api_key_env] = f"${{{tb.llm.api_key_env}:-}}"  # read from the host at `up`
    return env


def server_command(tb: Testbed, s: Server) -> list[str]:
    """The stdio server, exposed over Streamable HTTP by mcp-proxy (behind the auth proxy if needed)."""
    if needs_token(tb, s):
        return ["python3", "/opt/mcl/authproxy.py", "--", "mcp-proxy", "--host", "127.0.0.1",
                "--port", str(INNER_PORT), "--pass-environment", "--", f"mcp-{s.id}", *s.args]
    return ["mcp-proxy", "--host", "0.0.0.0", "--port", str(HTTP_PORT), "--pass-environment",
            "--", f"mcp-{s.id}", *s.args]


def server_service(tb: Testbed, s: Server) -> dict:
    env = {**s.env, **netem_env(s)}
    if needs_token(tb, s):
        env["MCL_TOKEN"] = domain_token(tb, s.domain)
    if "MCL_TRANSFORM" in s.env:  # transformer servers call the testbed's LLM
        env.update(llm_env(tb))
    svc = {
        "build": {"context": "context", "dockerfile": f"../dockerfiles/{s.id}.Dockerfile"},
        "image": f"mcl-{tb.testbed}-{s.id}",
        "command": server_command(tb, s),
        "environment": env,
        "networks": [network_name(s.domain)],
        "labels": {"mcl.role": "server", "mcl.label": s.label, "mcl.transport": "http"},
    }
    if s.has_volume:
        svc["volumes"] = [f"./data/{s.id}:{s.mount}"]
    if env.keys() & {"MCL_DELAY_MS", "MCL_LOSS_PCT"}:
        svc["cap_add"] = ["NET_ADMIN"]
    if not env:
        del svc["environment"]
    return svc


def client_endpoints(tb: Testbed, c: Client) -> dict:
    """How the client reaches each of its servers (MCL_SERVERS)."""
    via_gateway = tb.gateway.guard != "none"
    out = {}
    for s in (tb.server(x) for x in c.servers):
        if s.transport == "stdio":
            out[s.id] = {"transport": "stdio", "command": [f"mcp-{s.id}", *s.args], "env": s.env}
            continue
        url = (f"http://gateway:{HTTP_PORT}/{s.id}/mcp" if via_gateway else f"http://{s.id}:{HTTP_PORT}/mcp")
        spec = {"transport": "http", "url": url}
        if needs_token(tb, s):
            spec["headers"] = {"Authorization": f"Bearer {domain_token(tb, s.domain)}"}
        out[s.id] = spec
    return out


def client_service(tb: Testbed, c: Client, runs: Path) -> dict:
    servers = [tb.server(x) for x in c.servers]
    local = [s for s in servers if s.transport == "stdio"]
    remote = [s for s in servers if s.transport == "http"]
    mounts = {}
    for s in local:  # stdio servers run inside the client container, so their data is mounted here
        if s.has_volume:
            m = s.mount
            if m in mounts:
                raise TestbedError(f"client '{c.id}': servers '{mounts[m]}' and '{s.id}' both mount {m}")
            mounts[m] = s.id
    env = {"MCL_SERVERS": json.dumps(client_endpoints(tb, c)), **llm_env(tb)}
    for s in local:  # stdio transformers need the LLM too; keys already passed by llm_env
        env.update({k: v for k, v in s.env.items() if k.startswith("MCL_") and k not in env})
    svc = {
        "build": {"context": "context", "dockerfile": f"../dockerfiles/{c.id}.Dockerfile"},
        "image": f"mcl-{tb.testbed}-{c.id}",
        "command": ["sleep", "infinity"],  # tasks are started by `mcl run` with docker exec
        "environment": env,
        "labels": {"mcl.role": "client", "mcl.harness": c.harness},
        "init": True,
        "volumes": [f"{runs}:/runs"] + [f"./data/{sid}:{m}" for m, sid in mounts.items()],
    }
    if tb.gateway.guard != "none":
        svc["networks"] = [GATEWAY_NET]
    else:
        nets = sorted({network_name(s.domain) for s in remote})
        if nets:
            svc["networks"] = nets
    if c.replicas > 1:
        svc["deploy"] = {"replicas": c.replicas}
    return svc


def gateway_service(tb: Testbed, runs: Path) -> dict:
    http = [s for s in tb.servers if s.transport == "http"]
    config = {"guard": tb.gateway.guard,
              "servers": {s.id: {"label": s.label, "domain": s.domain} for s in http}}
    return {
        "build": {"context": "context", "dockerfile": "../dockerfiles/gateway.Dockerfile"},
        "image": f"mcl-{tb.testbed}-gateway",
        "command": ["python3", "/opt/mcl/gateway.py", "serve"],
        "environment": {"MCL_GATEWAY": json.dumps(config)},
        "volumes": ["./policy:/policy", f"{runs}:/runs"],
        "networks": sorted({network_name(s.domain) for s in http} | {GATEWAY_NET}),
        "labels": {"mcl.role": "gateway", "mcl.guard": tb.gateway.guard},
    }


def service_service(tb: Testbed, v: Service, runs: Path) -> dict:
    svc = {"networks": [network_name(v.domain)],
           "labels": {"mcl.role": "service", "mcl.label": v.label}}
    if v.image:
        svc["image"] = v.image
    else:  # builtin webhook-sink: records every request in runs/<testbed>/_sinks/<id>.jsonl
        svc |= {"build": {"context": "context", "dockerfile": "../dockerfiles/sink.Dockerfile"},
                "image": f"mcl-{tb.testbed}-sink",
                "command": ["python3", "/opt/mcl/sink.py", f"/runs/_sinks/{v.id}.jsonl"],
                "volumes": [f"{runs}:/runs"]}
    if v.env:
        svc["environment"] = dict(v.env)
    return svc


def tree_sha256(root: Path) -> str:
    """Hash of every file under a folder (names and contents), to identify a custom server's code."""
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(root)).encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        return out + ("-dirty" if dirty else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def initial_policy(loaded: Loaded) -> dict:
    tb = loaded.testbed
    servers = {s.id: {"label": s.label} for s in tb.servers}
    policy = default_policy(servers)
    if tb.gateway.policy:
        f = loaded.path.parent / tb.gateway.policy
        if not f.is_file():
            raise TestbedError(f"gateway.policy '{tb.gateway.policy}' not found next to {loaded.path.name}")
        policy.update(yaml.safe_load(f.read_text()) or {})
        unknown = [x for x in policy["sources"] + policy["sinks"] if x not in servers]
        if unknown:
            raise TestbedError(f"gateway.policy: unknown servers {unknown}")
    return policy


def build(loaded: Loaded, out: Path, runs: Path | None = None) -> Path:
    tb = loaded.testbed
    check_buildable(tb)
    out = out.resolve()
    runs = (runs or out.parent.parent / "runs" / tb.testbed).resolve()
    (runs / "_sinks").mkdir(parents=True, exist_ok=True)
    if out.exists():
        shutil.rmtree(out)
    (out / "dockerfiles").mkdir(parents=True)
    shutil.copytree(RUNTIME, out / "context")
    for m in CONTAINER_MODULES:
        shutil.copy(PACKAGE / m, out / "context" / m)
    for s in tb.servers:
        if s.runtime == "local":
            shutil.copytree(loaded.path.parent / s.path, out / "context" / "servers" / s.id,
                            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "*.db"))

    # Data and canaries.
    canaries = make_canaries(tb, loaded.path.parent)
    for s in tb.servers:
        if not s.has_volume:
            continue
        d = out / "data" / s.id
        if s.data and s.data.source:
            shutil.copytree(loaded.path.parent / s.data.source, d)
        d.mkdir(parents=True, exist_ok=True)
        mine = [r for r in canaries if r["server"] == s.id and r["file"]]
        if mine:
            (d / tb.canaries.file).write_text(canary_file_text(mine), encoding="utf-8")
    if (out / "data").exists():
        shutil.copytree(out / "data", out / "data.pristine")
    (out / "canaries.json").write_text(json.dumps(canaries, indent=1, ensure_ascii=False), encoding="utf-8")

    # Containers.
    services = {}
    for s in tb.servers:
        if s.transport == "http":
            (out / "dockerfiles" / f"{s.id}.Dockerfile").write_text(dockerfile([s], server_command(tb, s)))
            services[s.id] = server_service(tb, s)
    for c in tb.clients:
        local = [tb.server(x) for x in c.servers if tb.server(x).transport == "stdio"]
        (out / "dockerfiles" / f"{c.id}.Dockerfile").write_text(dockerfile(local, ["sleep", "infinity"]))
        services[c.id] = client_service(tb, c, runs)
    if tb.gateway.guard != "none":
        (out / "policy").mkdir()
        (out / "policy" / "current.json").write_text(json.dumps(initial_policy(loaded), indent=1))
        (out / "dockerfiles" / "gateway.Dockerfile").write_text(dockerfile([], ["python3", "/opt/mcl/gateway.py", "serve"]))
        services["gateway"] = gateway_service(tb, runs)
    if any(v.builtin for v in tb.services):
        (out / "dockerfiles" / "sink.Dockerfile").write_text(dockerfile([], ["python3", "/opt/mcl/sink.py"]))
    for v in tb.services:
        services[v.id] = service_service(tb, v, runs)

    used = {n for svc in services.values() for n in svc.get("networks", [])}
    networks = {network_name(d.id): {"internal": not d.internet} for d in tb.domains
                if network_name(d.id) in used}
    if GATEWAY_NET in used:
        networks[GATEWAY_NET] = {"internal": True}  # clients reach only the gateway
    compose = {"name": f"mcl-{tb.testbed}", "services": services}
    if networks:
        compose["networks"] = networks
    (out / "docker-compose.yml").write_text(
        f"# Generated by mcp-cybernet-lab {__version__} from {loaded.path.name}. Do not edit; edit the YAML and rebuild.\n"
        + yaml.safe_dump(compose, sort_keys=False, allow_unicode=True)
    )

    manifest = {
        "testbed": tb.testbed,
        "source": str(loaded.path),
        "source_sha256": loaded.sha256,
        "seed": tb.seed,
        "version": __version__,
        "commit": _git_commit(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_images": [BASE_IMAGE, UV_IMAGE],
        "mcp_proxy": MCP_PROXY,
        "runs": str(runs),
        "llm": tb.llm.model_dump(),
        "gateway": tb.gateway.model_dump(),
        "domains": [d.model_dump() for d in tb.domains],
        "servers": [{"id": s.id, "package": s.package, "path": s.path,
                     "source_sha256": tree_sha256(out / "context" / "servers" / s.id) if s.path else None,
                     "runtime": s.runtime,
                     "requested_version": s.version, "transport": s.transport,
                     "domain": s.domain, "label": s.label,
                     "attack": s.env.get("MCL_ATTACK"), "transform": s.env.get("MCL_TRANSFORM")}
                    for s in tb.servers],
        "services": [{"id": v.id, "image": v.image, "builtin": v.builtin, "domain": v.domain, "label": v.label}
                     for v in tb.services],
        "canaries": len(canaries),
        "warnings": loaded.warnings,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    return out
