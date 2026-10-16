"""Compile a testbed into a build folder: Dockerfiles, docker-compose.yml, seeded data, manifest.

build/<testbed>/
  docker-compose.yml
  context/                 runtime files copied into every image
  dockerfiles/<service>.Dockerfile
  data/<server>/           what each server sees at its mount point (canaries planted)
  data.pristine/           copy of data/, restored by `mcpnet reset`
  canaries.json            ground truth: every planted canary and where it lives
  manifest.json            what was built, from which file, with which seed
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import __version__
from .loader import Loaded, TestbedError, check_buildable
from .schema import Client, Server, Testbed
from .seeding import canary_file_text, make_canaries

REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / "images" / "runtime"
HTTP_PORT = 8080
MCP_PROXY = "mcp-proxy==0.13.0"
BASE_IMAGE = "node:22-bookworm-slim"
UV_IMAGE = "ghcr.io/astral-sh/uv:0.9.5"


def network_name(domain: str) -> str:
    return f"net-{domain}"


def server_url(s: Server) -> str:
    return f"http://{s.id}:{HTTP_PORT}/mcp"


def dockerfile(installs: list[Server], cmd: list[str]) -> str:
    lines = [
        f"FROM {BASE_IMAGE}",
        "RUN apt-get update && apt-get install -y --no-install-recommends \\",
        "      python3 python3-venv git iproute2 ca-certificates \\",
        " && rm -rf /var/lib/apt/lists/*",
        f"COPY --from={UV_IMAGE} /uv /uvx /usr/local/bin/",
        "ENV UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin UV_PYTHON_PREFERENCE=only-system",
        f"RUN uv tool install {MCP_PROXY}",
        "COPY install_server.py entrypoint.sh probe.py /opt/mcpnet/",
        "RUN chmod +x /opt/mcpnet/*.sh /opt/mcpnet/*.py",
    ]
    for s in installs:
        lines.append(f"RUN python3 /opt/mcpnet/install_server.py {s.runtime} {s.package} {s.version or '-'} {s.id}"
                     + "".join(f" '{w}'" for w in s.with_packages))
    lines.append('ENTRYPOINT ["/opt/mcpnet/entrypoint.sh"]')
    lines.append(f"CMD {json.dumps(cmd)}")
    return "\n".join(lines) + "\n"


def netem_env(s: Server) -> dict[str, str]:
    n = s.network
    if n.is_default:
        return {}
    env = {}
    if n.delay_ms or n.jitter_ms:
        env["MCPNET_DELAY_MS"] = str(n.delay_ms)
        env["MCPNET_JITTER_MS"] = str(n.jitter_ms)
    if n.loss:
        env["MCPNET_LOSS_PCT"] = f"{n.loss * 100:g}"
    return env


def server_command(s: Server) -> list[str]:
    """The stdio server, exposed over Streamable HTTP by mcp-proxy."""
    return ["mcp-proxy", "--host", "0.0.0.0", "--port", str(HTTP_PORT), "--pass-environment",
            "--", f"mcp-{s.id}", *s.args]


def server_service(tb: Testbed, s: Server) -> dict:
    svc = {
        "build": {"context": "context", "dockerfile": f"../dockerfiles/{s.id}.Dockerfile"},
        "image": f"mcpnet-{tb.testbed}-{s.id}",
        "command": server_command(s),
        "environment": {**s.env, **netem_env(s)},
        "networks": [network_name(s.domain)],
        "labels": {"mcpnet.role": "server", "mcpnet.label": s.label, "mcpnet.transport": "http"},
    }
    if s.has_volume:
        svc["volumes"] = [f"./data/{s.id}:{s.mount}"]
    if svc["environment"].keys() & {"MCPNET_DELAY_MS", "MCPNET_LOSS_PCT"}:
        svc["cap_add"] = ["NET_ADMIN"]
    if not svc["environment"]:
        del svc["environment"]
    return svc


def client_service(tb: Testbed, c: Client) -> dict:
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
    svc = {
        "build": {"context": "context", "dockerfile": f"../dockerfiles/{c.id}.Dockerfile"},
        "image": f"mcpnet-{tb.testbed}-{c.id}",
        "command": ["sleep", "infinity"],  # harness "none": the container waits for `mcpnet smoke`/exec
        "environment": {
            "MCPNET_SERVERS": json.dumps(
                {s.id: {"transport": "stdio", "command": [f"mcp-{s.id}", *s.args]} for s in local}
                | {s.id: {"transport": "http", "url": server_url(s)} for s in remote}
            ),
        },
        "labels": {"mcpnet.role": "client", "mcpnet.harness": c.harness},
        "init": True,
    }
    nets = sorted({network_name(s.domain) for s in remote})
    if nets:
        svc["networks"] = nets
    if mounts:
        svc["volumes"] = [f"./data/{sid}:{m}" for m, sid in mounts.items()]
    if c.replicas > 1:
        svc["deploy"] = {"replicas": c.replicas}
    if tb.llm.api_key_env:
        svc["environment"][tb.llm.api_key_env] = f"${{{tb.llm.api_key_env}:-}}"  # read from host at `up`
    return svc


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        return out + ("-dirty" if dirty else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build(loaded: Loaded, out: Path) -> Path:
    tb = loaded.testbed
    check_buildable(tb)
    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "dockerfiles").mkdir(parents=True)
    shutil.copytree(RUNTIME, out / "context")
    shutil.copy(Path(__file__).parent / "probe.py", out / "context" / "probe.py")

    # Data and canaries.
    canaries = make_canaries(tb)
    for s in tb.servers:
        if not s.has_volume:
            continue
        d = out / "data" / s.id
        if s.data and s.data.source:
            shutil.copytree(loaded.path.parent / s.data.source, d)
        d.mkdir(parents=True, exist_ok=True)
        mine = [r for r in canaries if r["server"] == s.id]
        if mine:
            (d / tb.canaries.file).write_text(canary_file_text(mine))
    if (out / "data").exists():
        shutil.copytree(out / "data", out / "data.pristine")
    (out / "canaries.json").write_text(json.dumps(canaries, indent=1))

    # Services.
    services = {}
    for s in tb.servers:
        if s.transport == "http":
            (out / "dockerfiles" / f"{s.id}.Dockerfile").write_text(dockerfile([s], server_command(s)))
            services[s.id] = server_service(tb, s)
    for c in tb.clients:
        local = [tb.server(x) for x in c.servers if tb.server(x).transport == "stdio"]
        (out / "dockerfiles" / f"{c.id}.Dockerfile").write_text(dockerfile(local, ["sleep", "infinity"]))
        services[c.id] = client_service(tb, c)

    used = {network_name(s.domain) for s in tb.servers if s.transport == "http"}
    networks = {network_name(d.id): {"internal": not d.internet} for d in tb.domains
                if network_name(d.id) in used}
    compose = {"name": f"mcpnet-{tb.testbed}", "services": services}
    if networks:
        compose["networks"] = networks
    (out / "docker-compose.yml").write_text(
        f"# Generated by mcpnet {__version__} from {loaded.path.name}. Do not edit; edit the YAML and rebuild.\n"
        + yaml.safe_dump(compose, sort_keys=False)
    )

    manifest = {
        "testbed": tb.testbed,
        "source": str(loaded.path),
        "source_sha256": loaded.sha256,
        "seed": tb.seed,
        "mcpnet_version": __version__,
        "mcpnet_commit": _git_commit(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_images": [BASE_IMAGE, UV_IMAGE],
        "mcp_proxy": MCP_PROXY,
        "servers": [{"id": s.id, "package": s.package, "runtime": s.runtime,
                     "requested_version": s.version, "transport": s.transport,
                     "domain": s.domain, "label": s.label} for s in tb.servers],
        "canaries": len(canaries),
        "warnings": loaded.warnings,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return out
