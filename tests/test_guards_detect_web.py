"""Unit tests for the public defensive pieces: the taint guard, the leak detector, the run
statistics and the web-UI summary. Synthetic values only; no attack scenarios."""

from __future__ import annotations

import base64
from pathlib import Path

from mcp_cybernet_lab.detect import Detector
from mcp_cybernet_lab.guards import Taint, default_policy, make_guard, replay
from mcp_cybernet_lab.report import mcnemar_exact, wilson
from mcp_cybernet_lab.web import _summary

REPO = Path(__file__).resolve().parent.parent
SECRET = "sk_live_ABCDEFGHIJKLMNOP0123"


# --- detector ----------------------------------------------------------------------------
def test_detector_exact_and_encoded():
    d = Detector([{"id": "c1", "value": SECRET, "kind": "stripe"}])
    assert d.scan("here is " + SECRET)[0]["method"] == "exact"
    enc = base64.b64encode(SECRET.encode()).decode()
    assert d.scan("blob=" + enc)[0]["method"] == "encoded"
    assert d.scan("nothing sensitive here") == []


def test_detector_normalizes_arabic_digits():
    d = Detector([{"id": "c2", "value": "١٢٣٤٥٦٧٨٩٠", "kind": "ar_person"}])
    hit = d.scan("the id is 1234567890 in ascii")
    assert hit and hit[0]["method"] == "normalized"


# --- taint guard -------------------------------------------------------------------------
def _policy():
    return {"version": 0, "sources": ["hr"], "sinks": ["paste"],
            "patterns": [{"name": "stripe", "regex": r"sk_live_[A-Za-z0-9]{16,}"}],
            "values": [], "check_patterns_at_sinks": False}


def test_taint_blocks_secret_from_source_to_sink():
    g = Taint(_policy())
    g.on_result("hr", "query", {}, f"row: {SECRET}")        # learned from a private source
    allowed, reason = g.on_call("paste", "post", {"text": f"see {SECRET}"})
    assert not allowed and "tainted" in reason


def test_taint_allows_clean_call_and_ignores_non_source():
    g = Taint(_policy())
    g.on_result("web", "fetch", {}, f"public page mentions {SECRET}")  # not a source: not tainted
    assert g.on_call("paste", "post", {"text": "weekly newsletter"})[0] is True
    assert g.on_call("paste", "post", {"text": f"see {SECRET}"})[0] is True


def test_default_policy_from_labels():
    servers = {"hr": {"label": "private"}, "paste": {"label": "public"}, "mix": {"label": "mixed"}}
    p = default_policy(servers)
    assert p["sinks"] == ["paste"] and set(p["sources"]) == {"hr", "mix"}
    assert make_guard("taint", p).name == "taint"


def test_replay_resets_between_tasks():
    g = Taint(_policy())
    events = [
        {"type": "tool_call", "task": "t1", "server": "hr", "tool": "q", "arguments": {},
         "result_text": SECRET},
        {"type": "tool_call", "task": "t1", "server": "paste", "tool": "p",
         "arguments": {"text": SECRET}, "result_text": None},
        {"type": "tool_call", "task": "t2", "server": "paste", "tool": "p",
         "arguments": {"text": SECRET}, "result_text": None},
    ]
    out = replay(g, events)
    assert out[1]["replay_allowed"] is False   # same task: tainted value is blocked
    assert out[2]["replay_allowed"] is True    # new task: guard was reset, nothing tainted yet


# --- report statistics -------------------------------------------------------------------
def test_wilson_and_mcnemar():
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0.0 < hi < 0.4
    assert mcnemar_exact(0, 0) == 1.0
    assert 0.0 < mcnemar_exact(8, 1) < 0.05   # a clear, significant disagreement


# --- web summary -------------------------------------------------------------------------
def test_web_summary_ok_and_error(tmp_path):
    s = _summary(REPO / "testbeds" / "toy-local.yaml")
    assert s["ok"] and s["counts"]["servers"] == 2
    bad = tmp_path / "bad.yaml"
    bad.write_text("testbed: x\nservers: not-a-list\n")
    assert _summary(bad)["ok"] is False
