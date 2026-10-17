"""Guards: the decision logic the gateway applies to every tool call.

A guard sees the stream of tool calls and their results, and decides for each call whether it
may go through. Guards are pure (no I/O), so the same code runs live in the gateway and offline
when `mcl evolve` replays logged runs against a candidate policy.

Built in:
  passthrough  allows everything (measures the gateway's own effect)
  taint        verbatim taint tracking, the usual baseline: values matching a sensitive pattern
               in results from `sources` are remembered; a call to a `sinks` server whose
               arguments contain one of them is blocked.

Add a guard: subclass Guard, register it in GUARDS. Standard library only.
"""

from __future__ import annotations

import json
import re

DEFAULT_PATTERNS = [
    {"name": "stripe_key", "regex": r"sk_live_[A-Za-z0-9]{16,}"},
    {"name": "aws_access_key", "regex": r"AKIA[A-Z0-9]{16}"},
    {"name": "github_token", "regex": r"ghp_[A-Za-z0-9]{36}"},
    {"name": "saudi_iban", "regex": r"SA\d{22}"},
    {"name": "saudi_national_id", "regex": r"\b[12]\d{9}\b"},
]


def default_policy(servers: dict[str, dict]) -> dict:
    """Policy version 0: private servers are sources, public servers are sinks."""
    return {
        "version": 0,
        "sources": sorted(s for s, v in servers.items() if v["label"] in ("private", "mixed")),
        "sinks": sorted(s for s, v in servers.items() if v["label"] == "public"),
        "patterns": DEFAULT_PATTERNS,
        "values": [],  # literal strings that may never reach a sink
        "check_patterns_at_sinks": False,  # also block pattern matches never seen in a source
    }


class Guard:
    name = "base"

    def __init__(self, policy: dict):
        self.policy = policy
        self.reset()

    def reset(self) -> None:
        """Forget everything seen (called at the start of each task)."""

    def on_call(self, server: str, tool: str, arguments: dict) -> tuple[bool, str]:
        """(allowed, reason) for a tool call about to be sent."""
        return True, ""

    def on_result(self, server: str, tool: str, arguments: dict, text: str) -> None:
        """Observe the text a tool returned."""


class Passthrough(Guard):
    name = "passthrough"


class Taint(Guard):
    name = "taint"

    def __init__(self, policy: dict):
        self.regexes = [(p["name"], re.compile(p["regex"])) for p in policy.get("patterns", [])]
        super().__init__(policy)

    def reset(self):
        self.tainted: dict[str, str] = {}  # value -> "pattern@server"

    def on_result(self, server, tool, arguments, text):
        if server not in self.policy.get("sources", []):
            return
        for name, rx in self.regexes:
            for m in rx.finditer(text or ""):
                self.tainted.setdefault(m.group(0), f"{name}@{server}")

    def on_call(self, server, tool, arguments):
        if server not in self.policy.get("sinks", []):
            return True, ""
        blob = json.dumps(arguments, ensure_ascii=False)
        for value, origin in self.tainted.items():
            if value in blob:
                return False, f"tainted value from {origin} sent to sink {server}"
        for value in self.policy.get("values", []):
            if value and value in blob:
                return False, f"listed value sent to sink {server}"
        if self.policy.get("check_patterns_at_sinks"):
            for name, rx in self.regexes:
                if rx.search(blob):
                    return False, f"{name} pattern sent to sink {server}"
        return True, ""


GUARDS = {g.name: g for g in (Passthrough, Taint)}


def make_guard(name: str, policy: dict) -> Guard:
    return GUARDS[name](policy)


def replay(guard: Guard, events: list[dict]) -> list[dict]:
    """Decisions of `guard` on logged tool-call events, in order, task by task.

    events: gateway log lines with type "tool_call": task, server, tool, arguments, result_text,
    decision. A call that was blocked when logged has no result to replay; if the guard now
    allows it, its result is unknown and simply not observed.
    """
    out, task = [], None
    for e in events:
        if e.get("type") != "tool_call":
            continue
        if e.get("task") != task:
            task = e.get("task")
            guard.reset()
        allowed, reason = guard.on_call(e["server"], e["tool"], e.get("arguments") or {})
        if allowed and e.get("result_text") is not None:
            guard.on_result(e["server"], e["tool"], e.get("arguments") or {}, e["result_text"])
        out.append({**e, "replay_allowed": allowed, "replay_reason": reason})
    return out
