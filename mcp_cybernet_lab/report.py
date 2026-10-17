"""Summaries of runs: rates with 95% Wilson intervals, and paired comparison of two runs.

A paired comparison (same tasks, two topologies or two guards) uses the exact McNemar test on
the tasks where the two runs disagree.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact p-value: b and c are the counts of the two kinds of disagreement."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def load_results(run: Path) -> list[dict]:
    path = run / "results.jsonl" if run.is_dir() else run
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def rate(rows, key) -> str:
    k, n = sum(bool(r[key]) for r in rows), len(rows)
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.1%} [95% CI {lo:.1%}–{hi:.1%}]" if n else "0/0"


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    calls = sum(r["tool_calls"] for r in rows)
    tokens = sum((r.get("tokens") or {}).get("prompt_tokens", 0) + (r.get("tokens") or {}).get("completion_tokens", 0)
                 for r in rows)
    return {
        "task_runs": n,
        "leak_rate": rate(rows, "leaked"),
        "attempt_rate": rate(rows, "attempted"),
        "completion_rate": rate(rows, "completed"),
        "blocked_calls": sum(r["blocked"] for r in rows),
        "false_alarms": sum(r["false_alarms"] for r in rows),
        "tool_calls": calls,
        "errors": sum(bool(r["error"]) for r in rows),
        "tokens": tokens,
        "mean_seconds": round(sum(r.get("seconds", 0) for r in rows) / n, 1) if n else 0,
    }


def report(run: Path) -> str:
    rows = load_results(run)
    s = summarize(rows)
    lines = [f"Run {run.name}: {s['task_runs']} task runs"]
    for k in ("leak_rate", "attempt_rate", "completion_rate"):
        lines.append(f"  {k.replace('_', ' '):16s} {s[k]}")
    lines.append(f"  blocked calls    {s['blocked_calls']}   false alarms {s['false_alarms']}   "
                 f"tool calls {s['tool_calls']}   agent errors {s['errors']}")
    lines.append(f"  tokens           {s['tokens']}   mean seconds per task {s['mean_seconds']}")
    fam = defaultdict(list)
    for r in rows:
        fam[r.get("family") or "-"].append(r)
    if len(fam) > 1:
        lines.append("  by family:")
        for f, rs in sorted(fam.items()):
            lines.append(f"    {f:24s} leaks {sum(r['leaked'] for r in rs)}/{len(rs)}   "
                         f"blocked {sum(r['blocked'] for r in rs)}   false alarms {sum(r['false_alarms'] for r in rs)}")
    methods = defaultdict(int)
    for r in rows:
        for leak in r["leaks"]:
            for h in leak["canaries"]:
                methods[h["method"]] += 1
    if methods:
        lines.append("  leaked canaries by detection method: " +
                     ", ".join(f"{m} {c}" for m, c in sorted(methods.items())))
    if run.is_dir():
        (run / "summary.json").write_text(json.dumps(s, indent=1))
    return "\n".join(lines)


def compare(run_a: Path, run_b: Path, key: str = "leaked") -> str:
    a = {(r["task"], r.get("repeat", 0)): bool(r[key]) for r in load_results(run_a)}
    b = {(r["task"], r.get("repeat", 0)): bool(r[key]) for r in load_results(run_b)}
    pairs = sorted(a.keys() & b.keys())
    if not pairs:
        return "no common task runs to compare"
    only_a = sum(a[p] and not b[p] for p in pairs)
    only_b = sum(b[p] and not a[p] for p in pairs)
    both = sum(a[p] and b[p] for p in pairs)
    ka, kb = sum(a[p] for p in pairs), sum(b[p] for p in pairs)
    return "\n".join([
        f"Paired comparison on '{key}', {len(pairs)} common task runs",
        f"  {run_a.name}: {ka}/{len(pairs)}    {run_b.name}: {kb}/{len(pairs)}",
        f"  both {both}, only {run_a.name} {only_a}, only {run_b.name} {only_b}",
        f"  exact McNemar p = {mcnemar_exact(only_a, only_b):.4g}",
    ])
