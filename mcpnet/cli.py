"""mcpnet command line.

    mcpnet validate testbeds/toy.yaml        check the file; no Docker needed
    mcpnet build    testbeds/toy.yaml        write build/<testbed>/ (compose, Dockerfiles, data, canaries)
    mcpnet up       testbeds/toy.yaml        build images and start the containers
    mcpnet smoke    testbeds/toy.yaml        from every client, initialize every server and list its tools
    mcpnet reset    testbeds/toy.yaml        restore every server's data to the planted state
    mcpnet down     testbeds/toy.yaml        stop and remove the containers and networks
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .compose import build
from .loader import TestbedError, check_buildable, load_testbed


def build_dir(args, name: str) -> Path:
    return Path(args.out) / name


def compose(out: Path, *cmd: str, capture: bool = False) -> subprocess.CompletedProcess:
    full = ["docker", "compose", "-f", str(out / "docker-compose.yml"), *cmd]
    return subprocess.run(full, capture_output=capture, text=True)


def need_build(out: Path) -> None:
    if not (out / "docker-compose.yml").exists():
        raise TestbedError(f"{out} is not built; run `mcpnet build` first")


def cmd_validate(args) -> int:
    loaded = load_testbed(args.testbed)
    tb = loaded.testbed
    for w in loaded.warnings:
        print(f"warning: {w}")
    http = sum(s.transport == "http" for s in tb.servers)
    print(f"ok: {tb.testbed} — {len(tb.servers)} servers ({http} http, {len(tb.servers) - http} stdio), "
          f"{len(tb.clients)} clients, {len(tb.domains)} domains, seed {tb.seed}")
    try:
        check_buildable(tb)
    except TestbedError as e:
        print(f"note: valid, but {e}")
    return 0


def cmd_build(args) -> int:
    loaded = load_testbed(args.testbed)
    for w in loaded.warnings:
        print(f"warning: {w}")
    out = build(loaded, build_dir(args, loaded.testbed.testbed))
    manifest = json.loads((out / "manifest.json").read_text())
    print(f"built {out} ({manifest['canaries']} canaries, commit {manifest['mcpnet_commit']})")
    return 0


def cmd_up(args) -> int:
    loaded = load_testbed(args.testbed)
    out = build_dir(args, loaded.testbed.testbed)
    need_build(out)
    return compose(out, "up", "-d", "--build", "--wait" if args.wait else "--quiet-pull").returncode


def cmd_smoke(args) -> int:
    loaded = load_testbed(args.testbed)
    tb = loaded.testbed
    out = build_dir(args, tb.testbed)
    need_build(out)
    results, failed = [], 0
    for c in tb.clients:
        for sid in c.servers:
            s = tb.server(sid)
            target = ["stdio", f"mcp-{s.id}", *s.args] if s.transport == "stdio" else \
                     ["http", f"http://{s.id}:8080/mcp"]
            r = compose(out, "exec", "-T", c.id, "python3", "/opt/mcpnet/probe.py", *target, capture=True)
            line = (r.stdout.strip().splitlines() or ['{"ok": false, "error": "no output"}'])[-1]
            try:
                res = json.loads(line)
            except json.JSONDecodeError:
                res = {"ok": False, "error": (r.stderr or line).strip()[-300:]}
            res["server_info"] = res.pop("server", None)  # name the server reports about itself
            res |= {"client": c.id, "server": s.id}
            results.append(res)
            failed += not res["ok"]
            status = "ok  " if res["ok"] else "FAIL"
            detail = (f"{res['server_info']} {res['version']} — {res['transport']}, {len(res['tools'])} tools, {res['ms']} ms"
                      if res["ok"] else res.get("error"))
            print(f"{status} {c.id} -> {s.id}: {detail}")

    # Record the versions actually installed, next to what the YAML asked for.
    installed = {}
    for svc in [s.id for s in tb.servers if s.transport == "http"] + [c.id for c in tb.clients]:
        r = compose(out, "exec", "-T", svc, "sh", "-c", "cat /opt/mcp/*/installed.json 2>/dev/null", capture=True)
        for chunk in r.stdout.replace("}{", "}\n{").splitlines():
            if chunk.strip():
                d = json.loads(chunk)
                installed[d["id"]] = d["version"]
    manifest = json.loads((out / "manifest.json").read_text())
    for s in manifest["servers"]:
        s["installed_version"] = installed.get(s["id"])
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (out / "smoke.json").write_text(json.dumps(results, indent=1))
    print(f"{len(results) - failed}/{len(results)} connections ok; results in {out / 'smoke.json'}")
    return 1 if failed else 0


def cmd_reset(args) -> int:
    loaded = load_testbed(args.testbed)
    out = build_dir(args, loaded.testbed.testbed)
    need_build(out)
    if not (out / "data.pristine").exists():
        print("nothing to reset (no server data)")
        return 0
    for d in (out / "data").iterdir():  # clear contents, keep the folders: they are bind-mounted
        for child in d.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        shutil.copytree(out / "data.pristine" / d.name, d, dirs_exist_ok=True)
    print(f"reset {out / 'data'}")
    return 0


def cmd_down(args) -> int:
    loaded = load_testbed(args.testbed)
    out = build_dir(args, loaded.testbed.testbed)
    need_build(out)
    return compose(out, "down", "--remove-orphans").returncode


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mcpnet", description="Containerised MCP network testbeds from one YAML file.")
    p.add_argument("--version", action="version", version=f"mcpnet {__version__}")
    p.add_argument("--out", default="build", help="folder for build outputs (default: build)")
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn in [("validate", cmd_validate), ("build", cmd_build), ("up", cmd_up),
                     ("smoke", cmd_smoke), ("reset", cmd_reset), ("down", cmd_down)]:
        sp = sub.add_parser(name)
        sp.add_argument("testbed", help="path to the testbed YAML file")
        if name == "up":
            sp.add_argument("--wait", action="store_true", help="wait until containers are running")
        sp.set_defaults(fn=fn)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except TestbedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
