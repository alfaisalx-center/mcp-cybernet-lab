#!/usr/bin/env python3
"""Install one MCP server package into its own folder and expose it as /usr/local/bin/mcp-<id>.

Run at image build time:  install_server.py <node|python> <package> <version|-> <id> [extra pins...]

The wrapper hides how each ecosystem names its executables, so the rest of mcpnet always
starts a server the same way: `mcp-<id> <args>`.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

runtime, package, version, sid = sys.argv[1:5]
extra = sys.argv[5:]  # pins of dependencies, for servers that break with the latest ones
version = None if version == "-" else version
prefix = Path("/opt/mcp") / sid
prefix.mkdir(parents=True, exist_ok=True)
wrapper = Path("/usr/local/bin") / f"mcp-{sid}"


def run(*cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


if runtime == "node":
    spec = f"{package}@{version}" if version else package
    run("npm", "install", "--omit=dev", "--no-audit", "--no-fund", "--prefix", str(prefix), spec, *extra)
    meta = json.loads((prefix / "node_modules" / package / "package.json").read_text())
    bins = meta.get("bin")
    if isinstance(bins, str):
        target = bins
    elif isinstance(bins, dict) and bins:
        target = next(iter(bins.values()))
    else:
        sys.exit(f"{package}: no executable declared in package.json 'bin'")
    entry = prefix / "node_modules" / package / target
    command = f'exec node "{entry}" "$@"'
    installed = meta.get("version", "?")

elif runtime == "python":
    spec = f"{package}=={version}" if version else package
    run("uv", "venv", "--quiet", str(prefix / "venv"))
    py = str(prefix / "venv" / "bin" / "python")
    run("uv", "pip", "install", "--quiet", "--python", py, spec, *extra)
    probe = (
        "import importlib.metadata as m, json, sys;"
        f"d = m.distribution({package!r});"
        "eps = [e.name for e in d.entry_points if e.group == 'console_scripts'];"
        "print(json.dumps({'eps': eps, 'version': d.version}))"
    )
    info = json.loads(subprocess.check_output([py, "-c", probe], text=True))
    if not info["eps"]:
        sys.exit(f"{package}: no console script")
    # Prefer the script named like the package; otherwise the first one.
    name = package if package in info["eps"] else info["eps"][0]
    command = f'exec "{prefix / "venv" / "bin" / name}" "$@"'
    installed = info["version"]

else:
    sys.exit(f"unknown runtime {runtime}")

wrapper.write_text(f"#!/bin/sh\n{command}\n")
wrapper.chmod(0o755)
# Record what was actually installed; mcpnet copies these into the run manifest.
(prefix / "installed.json").write_text(json.dumps({"id": sid, "package": package, "version": installed}))
print(f"installed {package} {installed} as {wrapper}")
os._exit(0)
