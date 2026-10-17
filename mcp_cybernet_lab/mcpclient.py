"""A small MCP client: stdio and Streamable HTTP sessions, initialize / tools/list / tools/call.

Standard library only, because it runs inside the client containers. Enough for the lab's agent;
not a general-purpose SDK (no sampling, roots or resumable streams).
"""

from __future__ import annotations

import itertools
import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"
CLIENT_INFO = {"name": "mcl-agent", "version": "0.2"}


class MCPError(Exception):
    """The server answered with a JSON-RPC error (also used when the gateway blocks a call)."""

    def __init__(self, error: dict):
        self.error = error
        super().__init__(error.get("message", str(error)))


class Session:
    """Common JSON-RPC logic; subclasses implement _send(msg) -> response or None."""

    def __init__(self, timeout: float = 120):
        self.timeout = timeout
        self._ids = itertools.count(1)
        self.server_info: dict = {}

    def request(self, method: str, params: dict | None = None) -> dict:
        msg = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}}
        resp = self._send(msg)
        if "error" in resp:
            raise MCPError(resp["error"])
        return resp["result"]

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict:
        result = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                             "clientInfo": CLIENT_INFO})
        self.server_info = result.get("serverInfo", {})
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += result.get("tools", [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        pass


class StdioSession(Session):
    def __init__(self, command: list[str], env: dict | None = None, timeout: float = 120):
        super().__init__(timeout)
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        self._lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _send(self, msg: dict) -> dict | None:
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if "id" not in msg:
            return None
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no response to {msg['method']} within {self.timeout}s")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise ConnectionError("server process exited")
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue  # log output on stdout
            if data.get("id") == msg["id"] and ("result" in data or "error" in data):
                return data

    def close(self):
        self.proc.kill()


class HttpSession(Session):
    def __init__(self, url: str, headers: dict | None = None, timeout: float = 120,
                 wait_s: float = 60):
        super().__init__(timeout)
        self.url = url
        self.headers = dict(headers or {})
        self.session_id: str | None = None
        self.wait_s = wait_s  # retry while the server is still starting

    def _send(self, msg: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL, **self.headers}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), headers=headers, method="POST")
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                r = urllib.request.urlopen(req, timeout=self.timeout)
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                try:  # a JSON-RPC error carried by an HTTP error status (e.g. 401 from auth)
                    data = json.loads(body)
                    if "error" in data:
                        return data
                except json.JSONDecodeError:
                    pass
                raise ConnectionError(f"HTTP {e.code} from {self.url}: {body[:200]}") from None
            except urllib.error.URLError as e:
                if not isinstance(e.reason, ConnectionRefusedError) or time.monotonic() > deadline:
                    raise
                time.sleep(1)
        with r:
            self.session_id = r.headers.get("Mcp-Session-Id", self.session_id)
            if "id" not in msg:
                r.read()
                return None
            if r.headers.get("Content-Type", "").startswith("text/event-stream"):
                for raw in r:  # read events until our response arrives
                    line = raw.decode().rstrip("\r\n")
                    if line.startswith("data:"):
                        data = json.loads(line[5:].strip())
                        if data.get("id") == msg["id"] and ("result" in data or "error" in data):
                            return data
                raise ConnectionError("event stream ended without a response")
            return json.loads(r.read().decode())

    def close(self):
        if self.session_id:  # end the session politely; ignore failures
            try:
                h = {**self.headers, "Mcp-Session-Id": self.session_id}
                urllib.request.urlopen(urllib.request.Request(self.url, headers=h, method="DELETE"), timeout=5)
            except Exception:
                pass


def open_session(spec: dict, timeout: float = 120) -> Session:
    """spec: {"transport": "stdio", "command": [...]} or {"transport": "http", "url": ..., "headers": {...}}"""
    if spec["transport"] == "stdio":
        env = {**os.environ, **spec.get("env", {})} if spec.get("env") else None
        return StdioSession(spec["command"], env=env, timeout=timeout)
    return HttpSession(spec["url"], spec.get("headers"), timeout=timeout)


def result_text(result: dict) -> str:
    """The text an agent sees from a tools/call result."""
    parts = []
    for c in result.get("content", []):
        if c.get("type") == "text":
            parts.append(c["text"])
        elif c.get("type") == "resource":
            parts.append(c.get("resource", {}).get("text", ""))
        else:
            parts.append(f"[{c.get('type')} content]")
    if not parts and "structuredContent" in result:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    return "\n".join(parts)
