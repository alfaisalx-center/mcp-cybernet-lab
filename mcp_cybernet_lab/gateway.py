#!/usr/bin/env python3
"""The gateway: every MCP request from a client passes here, is logged, and is checked by a guard.

    gateway.py serve                      (container command)
    gateway.py ctl start <log path>       start a task: reset the guard, reload the policy, log here
    gateway.py ctl stop                   end the task (log closed)

Clients reach server <id> at http://gateway:8080/<id>/mcp. The gateway forwards to
http://<id>:8080/mcp, keeping the client's headers (so per-domain tokens still apply).
A blocked tool call is answered with a JSON-RPC error, code -32001, and never reaches the server.

Control runs on 127.0.0.1:9090, inside the container only: agents and servers cannot reach it.
Configuration: MCL_GATEWAY = {"guard": ..., "servers": {id: {"label", "domain"}}},
policy file /policy/current.json.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from guards import make_guard  # noqa: E402
from httpproxy import Proxy, jsonrpc_error, parse_messages, serve  # noqa: E402
from mcpclient import result_text  # noqa: E402

CONFIG = json.loads(os.environ.get("MCL_GATEWAY", '{"guard": "passthrough", "servers": {}}'))
POLICY_FILE = Path(os.environ.get("MCL_POLICY_FILE", "/policy/current.json"))
BLOCKED = -32001


class State:
    lock = threading.Lock()
    guard = None
    log = None
    task = None
    t0 = time.monotonic()
    pending: dict = {}  # JSON-RPC id -> (server, tool, arguments), per session


def load_guard():
    policy = json.loads(POLICY_FILE.read_text()) if POLICY_FILE.exists() else {}
    State.guard = make_guard(CONFIG["guard"], policy)
    return policy.get("version")


def write(**event):
    if State.log:
        event.update(t=round(time.monotonic() - State.t0, 3), task=State.task)
        State.log.write(json.dumps(event, ensure_ascii=False) + "\n")
        State.log.flush()


class Gateway(Proxy):
    def route(self):
        parts = self.path.split("/", 2)  # "", "<server>", "mcp..."
        if len(parts) < 3 or parts[1] not in CONFIG["servers"]:
            return None
        self.server_id = parts[1]
        return parts[1], 8080, "/" + parts[2]

    def before(self, body):
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            return None
        if not isinstance(msg, dict) or msg.get("method") != "tools/call":
            if isinstance(msg, dict) and msg.get("method"):
                write(type="message", server=self.server_id, method=msg["method"])
            return None
        params = msg.get("params") or {}
        tool, args = params.get("name"), params.get("arguments") or {}
        with State.lock:
            allowed, reason = State.guard.on_call(self.server_id, tool, args)
            key = (self.headers.get("Mcp-Session-Id"), msg.get("id"))
            State.pending[key] = (tool, args)
        if allowed:
            return None
        write(type="tool_call", server=self.server_id, tool=tool, arguments=args,
              decision="block", reason=reason, result_text=None)
        return jsonrpc_error(msg.get("id"), BLOCKED, f"blocked: {reason}", {"blocked": True})

    def after(self, body, status, ctype, resp):
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict) or msg.get("method") != "tools/call":
            return
        key = (self.headers.get("Mcp-Session-Id"), msg.get("id"))
        with State.lock:
            tool, args = State.pending.pop(key, (None, {}))
            text, is_error = None, None
            for m in parse_messages(resp, ctype):
                if m.get("id") == msg.get("id"):
                    if "result" in m:
                        text, is_error = result_text(m["result"]), bool(m["result"].get("isError"))
                    elif "error" in m:
                        text, is_error = f"error: {m['error'].get('message')}", True
            if text is not None and not is_error:
                State.guard.on_result(self.server_id, tool, args, text)
        write(type="tool_call", server=self.server_id, tool=tool, arguments=args, decision="allow",
              reason="", result_text=text, is_error=is_error, http_status=status)


class Control(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        cmd = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        with State.lock:
            if State.log:
                State.log.close()
                State.log = None
            if self.path == "/start":
                version = load_guard()
                path = Path(cmd["log"])
                path.parent.mkdir(parents=True, exist_ok=True)
                State.log, State.task, State.t0 = open(path, "w", encoding="utf-8"), cmd.get("task"), time.monotonic()
                State.pending.clear()
                write(type="start", guard=CONFIG["guard"], policy_version=version)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def ctl(args):
    if args[0] == "start":
        data = {"log": args[1], "task": args[2] if len(args) > 2 else None}
        path = "/start"
    else:
        data, path = {}, "/stop"
    req = urllib.request.Request(f"http://127.0.0.1:9090{path}", data=json.dumps(data).encode(), method="POST")
    print(urllib.request.urlopen(req, timeout=10).read().decode())


def main():
    if sys.argv[1:2] == ["ctl"]:
        return ctl(sys.argv[2:])
    load_guard()
    threading.Thread(target=serve(Control, 9090, "127.0.0.1").serve_forever, daemon=True).start()
    print(f"mcl-gateway: guard {CONFIG['guard']}, servers {sorted(CONFIG['servers'])}", flush=True)
    serve(Gateway, 8080).serve_forever()


if __name__ == "__main__":
    main()
