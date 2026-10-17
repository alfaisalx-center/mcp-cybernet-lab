"""Reverse-proxy core for MCP Streamable HTTP, shared by the gateway and the auth proxy.

POST requests (JSON-RPC) are buffered, so hooks can inspect and block them, and their responses
(JSON or a short event stream) are buffered too. GET streams (server-initiated messages) and
DELETE are passed through unchanged. Standard library only.
"""

from __future__ import annotations

import http.client
import json
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM_WAIT_S = 60
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
       "proxy-authorization", "proxy-authenticate", "content-length", "host"}


def jsonrpc_error(req_id, code: int, message: str, data: dict | None = None) -> bytes:
    err = {"code": code, "message": message}
    if data:
        err["data"] = data
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": err}).encode()


def parse_messages(body: bytes, content_type: str) -> list[dict]:
    """JSON-RPC messages in a response body: plain JSON, a JSON array, or an event stream."""
    text = body.decode("utf-8", errors="replace")
    try:
        if content_type.startswith("text/event-stream"):
            return [json.loads(line[5:].strip()) for line in text.splitlines()
                    if line.startswith("data:") and line[5:].strip()]
        data = json.loads(text) if text.strip() else []
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return []


class Proxy(BaseHTTPRequestHandler):
    """Subclass and override route(), before() and after()."""

    protocol_version = "HTTP/1.0"  # one request per connection: simple and enough for the lab
    server_version = "mcl-proxy"

    def log_message(self, fmt, *args):  # quiet: the lab writes its own logs
        pass

    # --- hooks -------------------------------------------------------------------------
    def route(self) -> tuple[str, int, str] | None:
        """(host, port, path) of the upstream, or None for 404."""
        raise NotImplementedError

    def before(self, body: bytes) -> bytes | None:
        """Called with a POST body. Return a JSON body to answer directly (blocked), or None."""
        return None

    def after(self, body: bytes, status: int, content_type: str, resp: bytes) -> None:
        """Called with a POST and its buffered response."""

    # --- plumbing ----------------------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type="application/json", headers=()):
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self, method: str):
        target = self.route()
        if target is None:
            return self._send(404, b'{"error": "unknown route"}')
        host, port, path = target
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else None
        if method == "POST":
            answer = self.before(body)
            if answer is not None:
                return self._send(200, answer)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        deadline = time.monotonic() + UPSTREAM_WAIT_S
        while True:  # the upstream may be restarting (mcl run restarts servers between tasks)
            conn = http.client.HTTPConnection(host, port, timeout=600)
            try:
                conn.request(method, path, body=body, headers=headers)
                r = conn.getresponse()
                break
            except (ConnectionRefusedError, socket.gaierror) as e:
                conn.close()
                if time.monotonic() > deadline:
                    return self._send(502, json.dumps({"error": f"upstream {host}:{port}: {e}"}).encode())
                time.sleep(0.5)
            except OSError as e:
                return self._send(502, json.dumps({"error": f"upstream {host}:{port}: {e}"}).encode())
        out_headers = [(k, v) for k, v in r.getheaders() if k.lower() not in HOP and k.lower() != "content-type"]
        ctype = r.getheader("Content-Type", "application/json")
        if method == "POST":
            resp = r.read()
            conn.close()
            self.after(body, r.status, ctype, resp)
            return self._send(r.status, resp, ctype, out_headers)
        # GET stream or DELETE: pass through as it arrives.
        self.send_response(r.status)
        for k, v in out_headers:
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        try:
            while chunk := r.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            conn.close()

    def do_POST(self):
        self._forward("POST")

    def do_GET(self):
        self._forward("GET")

    def do_DELETE(self):
        self._forward("DELETE")


def serve(handler: type[Proxy], port: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv
