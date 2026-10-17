#!/usr/bin/env python3
"""Token check in front of an MCP server (domains with `auth: token`).

    authproxy.py -- mcp-proxy --port 8081 ... -- mcp-<id> <args>

Starts the command (the server, listening on 127.0.0.1:8081), then listens on 0.0.0.0:8080 and
forwards only requests carrying `Authorization: Bearer $MCL_TOKEN`. Others get HTTP 401 with a
JSON-RPC error. Every refusal is printed, so it shows in `docker logs`.
"""

from __future__ import annotations

import hmac
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from httpproxy import Proxy, jsonrpc_error, serve  # noqa: E402

TOKEN = os.environ.get("MCL_TOKEN", "")
UPSTREAM = ("127.0.0.1", 8081)


class AuthProxy(Proxy):
    def _authorised(self) -> bool:
        got = self.headers.get("Authorization", "")
        return bool(TOKEN) and hmac.compare_digest(got, f"Bearer {TOKEN}")

    def route(self):
        return (*UPSTREAM, self.path)

    def _forward(self, method):
        if not self._authorised():
            print(f"mcl-auth: refused {method} {self.path} from {self.client_address[0]}", flush=True)
            return self._send(401, jsonrpc_error(None, -32002, "unauthorised: missing or wrong token"),
                              headers=[("WWW-Authenticate", "Bearer")])
        return super()._forward(method)


def main():
    if "--" not in sys.argv:
        sys.exit("usage: authproxy.py -- <server command>")
    cmd = sys.argv[sys.argv.index("--") + 1:]
    child = subprocess.Popen(cmd)
    srv = serve(AuthProxy, 8080)
    print(f"mcl-auth: token check on :8080 -> {UPSTREAM[0]}:{UPSTREAM[1]}", flush=True)
    try:
        srv.serve_forever()
    finally:
        child.terminate()


if __name__ == "__main__":
    main()
