"""Run tasks on a running testbed: reset, run the agent, collect logs, detect leaks.

For each task (and repeat):
  1. restore every server's data to the planted state; restart the servers (clears in-memory state);
  2. tell the gateway (if any) to start a new log and reset its guard;
  3. run the agent in the client container on the task;
  4. collect the agent trace, the gateway log and new sink records;
  5. detect leaks and append one line to results.jsonl.

runs/<testbed>/<run id>/
  manifest.json canaries.json policy.json tasks.yaml
  tasks/<task>.json              what the agent receives
  <task>-r<k>/trace.jsonl        agent events
  <task>-r<k>/summary.json
  <task>-r<k>/gateway.jsonl      gateway decisions (with a gateway)
  <task>-r<k>/sinks.jsonl        sink records during the task
  results.jsonl                  one line per task run
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .detect import Detector, analyse_task
from .loader import Loaded, TestbedError


def load_tasks(path: str | Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not tasks:
        raise TestbedError(f"{path}: expected a top-level 'tasks' list")
    ids = set()
    for t in tasks:
        if not isinstance(t, dict) or not t.get("id") or not t.get("prompt"):
            raise TestbedError(f"{path}: every task needs 'id' and 'prompt' ({t})")
        if t["id"] in ids:
            raise TestbedError(f"{path}: duplicate task id {t['id']}")
        ids.add(t["id"])
    return tasks


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


class Runner:
    def __init__(self, loaded: Loaded, build: Path, log=print):
        self.tb = loaded.testbed
        self.build = build
        self.manifest = json.loads((build / "manifest.json").read_text())
        self.runs = Path(self.manifest["runs"])
        self.canaries = json.loads((build / "canaries.json").read_text(encoding="utf-8"))
        self.detector = Detector(self.canaries)
        self.labels = {s.id: s.label for s in self.tb.servers}
        self.has_gateway = self.tb.gateway.guard != "none"
        self.log = log
        if self.tb.llm.provider == "none" or not self.tb.llm.model:
            raise TestbedError("the testbed has no llm (llm.provider and llm.model); `mcl run` needs one")
        clients = [c for c in self.tb.clients if c.harness == "agent"]
        if not clients:
            raise TestbedError("no client with harness 'agent'")
        self.client = clients[0].id

    # --- docker helpers ---------------------------------------------------------------
    def compose(self, *args, check=True, capture=True) -> subprocess.CompletedProcess:
        r = subprocess.run(["docker", "compose", "-f", str(self.build / "docker-compose.yml"), *args],
                           capture_output=capture, text=True)
        if check and r.returncode != 0:
            raise TestbedError(f"docker compose {' '.join(args[:3])} failed: {(r.stderr or r.stdout)[-400:]}")
        return r

    def running(self) -> set[str]:
        r = self.compose("ps", "--services", "--status", "running")
        return set(r.stdout.split())

    def reset_state(self, restart: bool) -> None:
        data, pristine = self.build / "data", self.build / "data.pristine"
        if pristine.exists():
            for d in data.iterdir():  # clear contents, keep the bind-mounted folders
                for child in d.iterdir():
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
                shutil.copytree(pristine / d.name, d, dirs_exist_ok=True)
        if restart:
            http = [s.id for s in self.tb.servers if s.transport == "http"]
            if http:
                self.compose("restart", *http)

    def sink_offsets(self) -> dict[str, int]:
        return {p.stem: len(read_jsonl(p)) for p in (self.runs / "_sinks").glob("*.jsonl")}

    def sink_new(self, before: dict[str, int]) -> list[dict]:
        out = []
        for p in (self.runs / "_sinks").glob("*.jsonl"):
            for r in read_jsonl(p)[before.get(p.stem, 0):]:
                out.append({**r, "sink": p.stem})
        return out

    # --- one run --------------------------------------------------------------------
    def run(self, tasks: list[dict], run_id: str | None = None, repeats: int = 1, restart: bool = True,
            policy_note: str | None = None, run_dir: Path | None = None) -> Path:
        need = {self.client} | ({"gateway"} if self.has_gateway else set())
        missing = need - self.running()
        if missing:
            raise TestbedError(f"containers not running: {sorted(missing)}; run `mcl up` first")
        run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        rd = run_dir or self.runs / run_id
        (rd / "tasks").mkdir(parents=True, exist_ok=True)
        for f in ("manifest.json", "canaries.json"):
            shutil.copy(self.build / f, rd / f)
        if self.has_gateway:
            shutil.copy(self.build / "policy" / "current.json", rd / "policy.json")
        (rd / "tasks.yaml").write_text(yaml.safe_dump({"tasks": tasks}, allow_unicode=True, sort_keys=False))
        rel = rd.relative_to(self.runs)
        results = rd / "results.jsonl"
        for t in tasks:
            (rd / "tasks" / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False))
        for k in range(repeats):
            for t in tasks:
                name = f"{t['id']}-r{k}"
                out = rd / name
                out.mkdir(exist_ok=True)
                t0 = time.monotonic()
                self.reset_state(restart)
                if self.has_gateway:
                    self.compose("exec", "-T", "gateway", "python3", "/opt/mcl/gateway.py", "ctl", "start",
                                 f"/runs/{rel}/{name}/gateway.jsonl", name)
                before = self.sink_offsets()
                r = self.compose("exec", "-T", self.client, "python3", "/opt/mcl/agent.py",
                                 "--task", f"/runs/{rel}/tasks/{t['id']}.json", "--out", f"/runs/{rel}/{name}",
                                 check=False)
                if self.has_gateway:
                    self.compose("exec", "-T", "gateway", "python3", "/opt/mcl/gateway.py", "ctl", "stop")
                time.sleep(0.5)  # let sinks flush
                sinks = self.sink_new(before)
                with open(out / "sinks.jsonl", "w", encoding="utf-8") as f:
                    for s in sinks:
                        f.write(json.dumps(s, ensure_ascii=False) + "\n")
                summary_path = out / "summary.json"
                summary = json.loads(summary_path.read_text()) if summary_path.exists() else \
                    {"error": f"agent exited {r.returncode}: {(r.stderr or r.stdout)[-300:]}"}
                summary["run"] = name
                res = analyse_task(self.detector, self.labels, read_jsonl(out / "trace.jsonl"),
                                   read_jsonl(out / "gateway.jsonl"), sinks, summary, t)
                res |= {"repeat": k, "seconds": round(time.monotonic() - t0, 1), "policy": policy_note}
                with open(results, "a", encoding="utf-8") as f:
                    f.write(json.dumps(res, ensure_ascii=False) + "\n")
                flag = "LEAK" if res["leaked"] else ("blocked" if res["attempted"] else "ok")
                self.log(f"{name:24s} {flag:8s} calls {res['tool_calls']:2d}  blocked {res['blocked']}  "
                         f"false alarms {res['false_alarms']}  completed {res['completed']}"
                         + (f"  error {res['error']}" if res['error'] else ""))
        return rd


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
