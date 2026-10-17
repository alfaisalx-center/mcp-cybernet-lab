#!/usr/bin/env python3
"""A minimal MCP client used to check that a server is up: initialize, then tools/list.

Standard library only, because it runs inside the client containers.

    probe.py stdio <command> [args...]
    probe.py http  <url>             # Streamable HTTP endpoint, e.g. http://fs:8080/mcp
    probe.py all                     # every server in $MCL_SERVERS (as the agent sees them:
                                     # through the gateway and with tokens when configured)

Prints one JSON line: {"ok", "transport", "server", "version", "protocol", "tools", "ms"}.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"
TIMEOUT_S = 60

INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": PROTOCOL, "capabilities": {},
               "clientInfo": {"name": "mcl-probe", "version": "0.1"}},
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def summary(transport: str, init: dict, tools: dict, t0: float) -> dict:
    info = init.get("result", {})
    return {
        "ok": "result" in init and "result" in tools,
        "transport": transport,
        "server": info.get("serverInfo", {}).get("name"),
        "version": info.get("serverInfo", {}).get("version"),
        "protocol": info.get("protocolVersion"),
        "tools": sorted(t["name"] for t in tools.get("result", {}).get("tools", [])),
        "ms": round((time.monotonic() - t0) * 1000),
    }


def probe_stdio(cmd: list[str]) -> dict:
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, bufsize=1)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l) for l in p.stdout], daemon=True).start()

    def send(msg):
        p.stdin.write(json.dumps(msg) + "\n")
        p.stdin.flush()

    def wait_for(mid):
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=deadline - time.monotonic())
            except queue.Empty:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers sometimes print logs on stdout
            if msg.get("id") == mid:
                return msg
        raise TimeoutError(f"no response to id {mid} within {TIMEOUT_S}s")

    try:
        send(INIT)
        init = wait_for(1)
        send(INITIALIZED)
        send(LIST_TOOLS)
        tools = wait_for(2)
        return summary("stdio", init, tools, t0)
    finally:
        p.kill()


def _post(url: str, msg: dict, session: str | None) -> tuple[dict | None, str | None]:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": PROTOCOL}
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, data=json.dumps(msg).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        session = r.headers.get("Mcp-Session-Id", session)
        body = r.read().decode()
        if "id" not in msg:
            return None, session  # notification: 202, no body
        if r.headers.get("Content-Type", "").startswith("text/event-stream"):
            for line in body.splitlines():
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if data.get("id") == msg["id"]:
                        return data, session
            raise ValueError("no matching response in the event stream")
        return json.loads(body), session


def probe_http(url: str) -> dict:
    t0 = time.monotonic()
    deadline = t0 + TIMEOUT_S
    while True:  # the server container may still be starting: retry while the port is closed
        try:
            init, session = _post(url, INIT, None)
            break
        except urllib.error.URLError as e:
            if not isinstance(e.reason, ConnectionRefusedError) or time.monotonic() > deadline:
                raise
            time.sleep(1)
    _post(url, INITIALIZED, session)
    tools, _ = _post(url, LIST_TOOLS, session)
    return summary("http", init, tools, t0)


def probe_all() -> int:
    """One JSON line per server of this client, using the agent's own client code."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mcpclient import open_session

    failed = 0
    for sid, spec in json.loads(os.environ["MCL_SERVERS"]).items():
        t0 = time.monotonic()
        try:
            s = open_session(spec, timeout=TIMEOUT_S)
            init = s.initialize()
            tools = s.list_tools()
            s.close()
            out = {"ok": True, "transport": spec["transport"],
                   "server": init.get("serverInfo", {}).get("name"),
                   "version": init.get("serverInfo", {}).get("version"),
                   "protocol": init.get("protocolVersion"), "tools": sorted(t["name"] for t in tools),
                   "ms": round((time.monotonic() - t0) * 1000)}
        except Exception as e:
            out = {"ok": False, "transport": spec["transport"], "error": f"{type(e).__name__}: {e}"}
            failed += 1
        print(json.dumps({"id": sid, **out}), flush=True)
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["all"]:
        return probe_all()
    if len(argv) < 2 or argv[0] not in ("stdio", "http"):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        out = probe_stdio(argv[1:]) if argv[0] == "stdio" else probe_http(argv[1])
    except Exception as e:  # report, do not crash: the caller collects one line per server
        out = {"ok": False, "transport": argv[0], "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
