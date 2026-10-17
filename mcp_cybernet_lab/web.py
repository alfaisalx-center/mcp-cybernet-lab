"""`mcl web` — a local web interface to configure and run testbeds. Standard library only.

A small HTTP server (bound to 127.0.0.1 by default) that serves the built React front-end and a
JSON API over the existing commands. It is a teaching and setup aid: edit a testbed YAML in the
browser, validate it, browse the server catalogue, and run build / up / smoke / down, watching the
output. Everything runs on the local machine against local Docker; nothing is exposed to a network.

    mcl web                 serve on http://127.0.0.1:8000, testbeds from ./testbeds
    mcl web --port 9000 --dir /path/to/project

The API (all JSON):
    GET  /api/info                      versions and paths
    GET  /api/testbeds                  list *.yaml under the testbeds dir
    GET  /api/catalogue                 the server catalogue (docs), if present
    GET  /api/testbed?name=toy-local    read one testbed: raw text + validate summary
    POST /api/validate  {yaml}          validate YAML text without saving
    POST /api/save      {name, yaml}    write YAML text to the testbeds dir
    POST /api/action    {name, action}  run mcl build|up|smoke|reset|down and return its output
    GET  /api/status?name=toy-local     docker compose ps for a built testbed
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .loader import TestbedError, load_testbed

ACTIONS = ("validate", "build", "up", "smoke", "reset", "down")
WEB_DIST = Path(__file__).parent / "webdist"  # the built React app, shipped with the package


def _summary(path: Path) -> dict:
    """Validate a testbed file and return a short, UI-friendly summary (or an error)."""
    try:
        loaded = load_testbed(path)
        tb = loaded.testbed
        http = sum(s.transport == "http" for s in tb.servers)
        return {
            "ok": True, "name": tb.testbed, "warnings": loaded.warnings,
            "servers": [{"id": s.id, "transport": s.transport, "label": s.label,
                         "domain": s.domain, "runtime": s.runtime} for s in tb.servers],
            "clients": [c.id for c in tb.clients], "domains": [d.id for d in tb.domains],
            "services": [s.id for s in tb.services], "gateway": tb.gateway.guard, "seed": tb.seed,
            "counts": {"servers": len(tb.servers), "http": http, "stdio": len(tb.servers) - http,
                       "clients": len(tb.clients), "domains": len(tb.domains), "services": len(tb.services)},
        }
    except (TestbedError, Exception) as e:  # noqa: BLE001 — any load error becomes a UI message
        return {"ok": False, "error": str(e)}


class Handler(BaseHTTPRequestHandler):
    # set per-server below
    testbeds_dir: Path = Path("testbeds")
    project_dir: Path = Path(".")
    catalogue: Path | None = None

    def log_message(self, *a):  # quieter console
        pass

    # --- helpers -------------------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _tb_path(self, name: str) -> Path:
        """Resolve a testbed name to a path inside the testbeds dir (no escaping)."""
        p = (self.testbeds_dir / Path(name).name).with_suffix(".yaml")
        if self.testbeds_dir.resolve() not in p.resolve().parents:
            raise TestbedError("invalid testbed name")
        return p

    def _mcl(self, action: str, name: str) -> dict:
        path = self._tb_path(name)
        cmd = [sys.executable, "-m", "mcp_cybernet_lab", action, str(path)]
        r = subprocess.run(cmd, cwd=self.project_dir, capture_output=True, text=True)
        return {"action": action, "name": name, "returncode": r.returncode,
                "stdout": r.stdout, "stderr": r.stderr}

    # --- routes --------------------------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/info":
            return self._json({"version": __version__, "testbeds_dir": str(self.testbeds_dir),
                               "project_dir": str(self.project_dir), "actions": list(ACTIONS)})
        if u.path == "/api/testbeds":
            files = sorted(self.testbeds_dir.glob("*.yaml")) if self.testbeds_dir.is_dir() else []
            return self._json([{"name": f.stem, "summary": _summary(f)} for f in files])
        if u.path == "/api/catalogue":
            text = self.catalogue.read_text(encoding="utf-8") if self.catalogue and self.catalogue.exists() else ""
            return self._json({"markdown": text})
        if u.path == "/api/testbed":
            name = (q.get("name") or [""])[0]
            try:
                path = self._tb_path(name)
            except TestbedError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            if not path.exists():
                return self._json({"ok": False, "error": f"{name} not found"}, 404)
            return self._json({"name": name, "yaml": path.read_text(encoding="utf-8"),
                               "summary": _summary(path)})
        if u.path == "/api/status":
            name = (q.get("name") or [""])[0]
            out = self.project_dir / "build" / name / "docker-compose.yml"
            if not out.exists():
                return self._json({"built": False, "ps": ""})
            r = subprocess.run(["docker", "compose", "-f", str(out), "ps"],
                               capture_output=True, text=True, cwd=self.project_dir)
            return self._json({"built": True, "ps": r.stdout or r.stderr})
        return self._serve_static(u.path)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        try:
            data = self._read_json()
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "invalid JSON body"}, 400)
        if u.path == "/api/validate":
            return self._json(self._validate_text(data.get("yaml", "")))
        if u.path == "/api/save":
            name = data.get("name", "")
            try:
                path = self._tb_path(name)
            except TestbedError as e:
                return self._json({"ok": False, "error": str(e)}, 400)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data.get("yaml", ""), encoding="utf-8")
            return self._json({"ok": True, "name": name, "summary": _summary(path)})
        if u.path == "/api/action":
            action, name = data.get("action"), data.get("name", "")
            if action not in ACTIONS:
                return self._json({"ok": False, "error": f"unknown action {action}"}, 400)
            if action == "validate":
                return self._json({"ok": True, **self._mcl(action, name)})
            return self._json({"ok": True, **self._mcl(action, name)})
        return self._json({"ok": False, "error": "not found"}, 404)

    def _validate_text(self, text: str) -> dict:
        tmp = self.testbeds_dir / ".__scratch__.yaml"
        try:
            tmp.write_text(text, encoding="utf-8")
            return _summary(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    # --- static (the built React app) ----------------------------------------------------
    def _serve_static(self, path: str):
        rel = path.lstrip("/") or "index.html"
        target = (WEB_DIST / rel).resolve()
        if WEB_DIST.resolve() not in target.parents and target != WEB_DIST.resolve():
            target = WEB_DIST / "index.html"  # SPA fallback, never escape the dist dir
        if not target.exists() or target.is_dir():
            target = WEB_DIST / "index.html"
        if not target.exists():
            return self._send(200, _PLACEHOLDER.encode(), "text/html; charset=utf-8")
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
                 ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json",
                 ".ico": "image/x-icon"}.get(target.suffix, "application/octet-stream")
        return self._send(200, target.read_bytes(), ctype)


_PLACEHOLDER = """<!doctype html><html><head><meta charset="utf-8"><title>MCP CyberNet Lab</title>
<style>body{font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;color:#1a2332}
code{background:#eef;padding:.1rem .3rem;border-radius:3px}</style></head><body>
<h1>MCP CyberNet Lab — web UI</h1>
<p>The front-end has not been built. From the repository root:</p>
<pre><code>cd web && npm install && npm run build</code></pre>
<p>That writes the app into <code>mcp_cybernet_lab/webdist/</code>. Reload this page afterwards.</p>
<p>The JSON API is live now — e.g. <a href="/api/testbeds">/api/testbeds</a>.</p>
</body></html>"""


def serve(testbeds_dir: Path, project_dir: Path, catalogue: Path | None,
          host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    Handler.testbeds_dir = testbeds_dir
    Handler.project_dir = project_dir
    Handler.catalogue = catalogue
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"MCP CyberNet Lab web UI on {url}  (testbeds: {testbeds_dir}, Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
