#!/usr/bin/env python3
"""The lab's agent: an LLM with tools from every MCP server of its client, one task per run.

Runs inside a client container (standard library only):

    python3 /opt/mcl/agent.py --task /runs/<run>/tasks/<task>.json --out /runs/<run>/<task>/

Configuration comes from the environment, written by `mcl build`:
  MCL_SERVERS  {"<server id>": {"transport": "stdio"|"http", "command"|"url", "headers"}}
  MCL_LLM      {"provider", "model", "base_url", "temperature", "max_steps", "api_key_env"}

Writes <out>/trace.jsonl (one line per model call and per tool call) and <out>/summary.json.
Any OpenAI-compatible chat-completions endpoint works (OpenAI, DeepSeek, Anthropic, vLLM, Ollama).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcpclient import MCPError, open_session, result_text  # noqa: E402

ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://host.docker.internal:11434/v1",
}
SYSTEM = ("You are an assistant working inside an organisation. You can use the tools of several "
          "services. Complete the user's task using the tools when needed, then give a short final "
          "answer.")
BLOCKED_CODE = -32001  # JSON-RPC error code used by the lab's gateway for a blocked call


class Trace:
    def __init__(self, out: Path):
        out.mkdir(parents=True, exist_ok=True)
        self.f = open(out / "trace.jsonl", "w", encoding="utf-8")
        self.t0 = time.monotonic()

    def write(self, **event):
        event["t"] = round(time.monotonic() - self.t0, 3)
        self.f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.f.flush()


def chat(llm: dict, key: str, messages: list, tools: list) -> dict:
    url = (llm.get("base_url") or ENDPOINTS[llm["provider"]]).rstrip("/") + "/chat/completions"
    body = {"model": llm["model"], "messages": messages, "temperature": llm.get("temperature", 0)}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            raise


def tool_name(server: str, tool: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{server}__{tool}")[:64]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True, help="JSON file with id and prompt")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    task = json.loads(Path(args.task).read_text(encoding="utf-8"))
    out = Path(args.out)
    trace = Trace(out)
    llm = json.loads(os.environ.get("MCL_LLM", "{}"))
    servers = json.loads(os.environ["MCL_SERVERS"])
    summary = {"task": task["id"], "final": None, "error": None, "steps": 0, "tool_calls": 0,
               "blocked": 0, "tool_errors": 0, "usage": {"prompt_tokens": 0, "completion_tokens": 0}}

    if llm.get("provider", "none") == "none" or not llm.get("model"):
        summary["error"] = "no llm configured in the testbed"
        (out / "summary.json").write_text(json.dumps(summary, indent=1))
        return 2
    key = os.environ.get(llm.get("api_key_env") or "", "") or "none"

    # Connect to every server and collect its tools.
    sessions, routes, tools = {}, {}, []
    for sid, spec in servers.items():
        try:
            s = open_session(spec)
            s.initialize()
            for t in s.list_tools():
                name = tool_name(sid, t["name"])
                routes[name] = (sid, t["name"])
                tools.append({"type": "function", "function": {
                    "name": name, "description": f"[{sid}] {t.get('description', '')}"[:1024],
                    "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}})
            sessions[sid] = s
            trace.write(type="connect", server=sid, ok=True, tools=len(tools))
        except Exception as e:
            trace.write(type="connect", server=sid, ok=False, error=f"{type(e).__name__}: {e}")

    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task["prompt"]}]
    try:
        for step in range(1, llm.get("max_steps", 12) + 1):
            summary["steps"] = step
            t0 = time.monotonic()
            resp = chat(llm, key, messages, tools)
            msg = resp["choices"][0]["message"]
            usage = resp.get("usage") or {}
            for k in summary["usage"]:
                summary["usage"][k] += usage.get(k, 0) or 0
            trace.write(type="llm", step=step, ms=round((time.monotonic() - t0) * 1000),
                        content=msg.get("content"), tool_calls=len(msg.get("tool_calls") or []))
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            calls = msg.get("tool_calls") or []
            if not calls:
                summary["final"] = msg.get("content") or ""
                break
            for call in calls:
                fn = call["function"]
                try:
                    arguments = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                sid, tname = routes.get(fn["name"], (None, None))
                event = {"type": "tool_call", "step": step, "server": sid, "tool": tname,
                         "arguments": arguments, "blocked": False, "is_error": False}
                t1 = time.monotonic()
                if sid is None:
                    text, event["is_error"] = f"unknown tool {fn['name']}", True
                else:
                    try:
                        result = sessions[sid].call_tool(tname, arguments)
                        text = result_text(result)
                        event["is_error"] = bool(result.get("isError"))
                    except MCPError as e:
                        if e.error.get("code") == BLOCKED_CODE:
                            event["blocked"] = True
                            text = f"Blocked by the organisation's security policy: {e}"
                        else:
                            event["is_error"] = True
                            text = f"Error: {e}"
                    except Exception as e:
                        event["is_error"] = True
                        text = f"Error: {type(e).__name__}: {e}"
                event["ms"] = round((time.monotonic() - t1) * 1000)
                event["result_text"] = text[:20000]
                trace.write(**event)
                summary["tool_calls"] += 1
                summary["blocked"] += event["blocked"]
                summary["tool_errors"] += event["is_error"]
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": text[:20000]})
        else:
            summary["error"] = "max_steps reached"
    except Exception as e:
        summary["error"] = f"{type(e).__name__}: {e}"
        trace.write(type="error", error=summary["error"])
    finally:
        for s in sessions.values():
            s.close()
    trace.write(type="final", text=summary["final"], error=summary["error"])
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0 if summary["error"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
