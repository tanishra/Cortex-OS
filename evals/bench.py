"""Benchmark runner: feed public Online-Mind2Web tasks through the real
runner, capture per-task metrics, save a scored JSON report.

Usage:
    python -m evals.bench [--limit N] [--level easy|medium|hard] [--task ID]
    python -m evals.bench --judge evals/benchmark/results/run_X.json
    python -m evals.bench --report evals/benchmark/results/run_X.json

Requires OPENAI_API_KEY for live runs. Failures are DATA, not errors —
the exit code only signals infra problems, never a low score.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from cortex.config import settings
from cortex.models import TaskRequest, TaskStatus
from cortex.store import db

BENCH_DIR = Path(__file__).parent / "benchmark"
TASKS_FILE = BENCH_DIR / "online_mind2web.jsonl"
RESULTS_DIR = BENCH_DIR / "results"

logger = logging.getLogger("cortex.bench")


def load_benchmark_tasks(
    path: Path = TASKS_FILE, level: str | None = None, limit: int | None = None
) -> list[dict]:
    """Load tasks from the Online-Mind2Web jsonl; filter by level, cap at limit."""
    tasks = []
    required = {"task_id", "confirmed_task", "website", "level"}
    for i, line in enumerate(path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        t = json.loads(line)
        missing = required - set(t)
        if missing:
            raise ValueError(f"task line {i + 1} missing fields: {missing}")
        if level and t["level"] != level:
            continue
        tasks.append(t)
        if limit and len(tasks) >= limit:
            break
    return tasks


def _metrics(row) -> dict:
    """Pull tokens/cost from the 'finished' event + exec time from step events."""
    events = db.list_events(row.id)
    tokens_in = tokens_out = None
    cost = None
    duration_ms = 0
    for e in events:
        if e.kind == "finished":
            tokens_in = e.tokens_in
            tokens_out = e.tokens_out
            cost = e.cost_usd
        elif e.kind == "step" and e.duration_ms:
            duration_ms += e.duration_ms
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
        "duration_s": round(duration_ms / 1000, 1),
    }


async def _run_case(
    task: dict, max_steps: int = 30, timeout_s: float = 300
) -> dict:
    from cortex.engine.runner import run_task

    req = TaskRequest(
        task=task["confirmed_task"],
        start_url=task["website"],
        max_steps=max_steps,
    )
    row, _ = db.create_task(req)
    try:
        # The worker has a job-level timeout; bench calls run_task directly,
        # so cap it here or a wandering agent burns tokens forever.
        await asyncio.wait_for(run_task(row.id), timeout=timeout_s)
    except TimeoutError:
        db.update_task(
            row.id, status=TaskStatus.FAILED, error="bench_timeout"
        )
    except Exception as exc:  # a crashed run is data too
        db.update_task(row.id, status=TaskStatus.FAILED, error=str(exc))
    row = db.get_task(row.id)
    rec = {
        "task_id": task["task_id"],
        "cortex_task_id": row.id,
        "website": task["website"],
        "level": task["level"],
        "task": task["confirmed_task"],
        "status": row.status,
        "steps": row.steps_taken,
        "retry_count": row.retry_count,
        "result": row.result,
        "error": (row.error or "")[:300],
        "verdict": "unscored",
    }
    rec.update(_metrics(row))
    return rec


def summarize(records: list[dict]) -> dict:
    total = len(records)
    passed = sum(1 for r in records if r["verdict"] == "pass")
    failed = sum(1 for r in records if r["verdict"] == "fail")
    unscored = total - passed - failed
    scored = passed + failed
    def _avg(key):
        vals = [r[key] for r in records if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _sum(key):
        vals = [r[key] for r in records if r.get(key) is not None]
        return round(sum(vals), 4) if vals else None

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "unscored": unscored,
        "success_rate": round(passed / scored, 3) if scored else None,
        "status_done": sum(1 for r in records if r["status"] == "done"),
        "status_failed": sum(1 for r in records if r["status"] == "failed"),
        "avg_steps": _avg("steps"),
        "avg_duration_s": _avg("duration_s"),
        "tokens_in_total": _sum("tokens_in"),
        "tokens_out_total": _sum("tokens_out"),
        "cost_usd_total": _sum("cost_usd"),
        "cost_usd_per_task": (
            round(_sum("cost_usd") / total, 4) if _sum("cost_usd") else None
        ),
    }


def _isolate_eval_state() -> None:
    """Same pattern as evals.run: benchmark tasks never pollute app state."""
    eval_dir = Path(__file__).parent
    settings.database_url = f"sqlite:///{eval_dir / 'evals.db'}"
    settings.artifacts_dir = eval_dir / "artifacts"
    settings.browser_profiles_dir = eval_dir / "profiles"
    from sqlmodel import create_engine

    db._ENGINE = create_engine(settings.database_url, echo=False)
    db.init_db()


def _print_table(records: list[dict]) -> None:
    print(f"{'task':<12} {'status':<10} {'steps':>5} {'tok_in':>7} "
          f"{'tok_out':>7} {'$':>7} {'s':>6} {'verdict':<9} site")
    for r in records:
        site = r["website"].replace("https://", "").replace("http://", "")[:30]
        print(
            f"{r['task_id'][:12]:<12} {r['status']:<10} {r['steps']:>5} "
            f"{r['tokens_in'] or '-':>7} {r['tokens_out'] or '-':>7} "
            f"{r['cost_usd'] if r['cost_usd'] is not None else '-':>7} "
            f"{r['duration_s']:>6} {r['verdict']:<9} {site}"
        )


async def run_bench(
    level: str | None,
    limit: int | None,
    task_id: str | None,
    max_steps: int = 30,
    timeout_s: float = 300,
    tasks_file: Path | None = None,
) -> dict:
    _isolate_eval_state()
    tasks = load_benchmark_tasks(level=level, limit=limit)
    if task_id:
        tasks = [t for t in load_benchmark_tasks() if t["task_id"] == task_id]
        if not tasks:
            raise ValueError(f"task_id {task_id} not found")
    if tasks_file:
        text = await asyncio.to_thread(tasks_file.read_text)
        wanted = [x.strip() for x in text.splitlines() if x.strip()]
        by_id = {t["task_id"]: t for t in load_benchmark_tasks()}
        missing = [w for w in wanted if w not in by_id]
        if missing:
            raise ValueError(f"task ids not in dataset: {missing}")
        tasks = [by_id[w] for w in wanted]
    results = []
    for t in tasks:
        logger.info("benchmark task %s — %s", t["task_id"][:8], t["website"])
        results.append(await _run_case(t, max_steps, timeout_s))
    report = {
        "meta": {
            "benchmark": "Online-Mind2Web (stagehand jsonl copy)",
            "model": settings.openai_model,
            "date": datetime.now(UTC).isoformat(),
            "level": level,
            "limit": limit,
            "max_steps": max_steps,
            "timeout_s": timeout_s,
            "scored": "manual",
        },
        "tasks": results,
        "summary": summarize(results),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"run_{int(time.time())}.json"
    out.write_text(json.dumps(report, indent=2))
    _print_table(results)
    print(f"\nReport: {out}")
    print("Score: python -m evals.bench --judge " + str(out))
    return report


def judge(path: Path) -> int:
    report = json.loads(path.read_text())
    for r in report["tasks"]:
        if r["verdict"] != "unscored":
            continue
        print(f"\n=== {r['task_id'][:12]} ({r['status']}, {r['steps']} steps) ===")
        print(f"TASK: {r['task']}")
        print(f"RESULT: {r['result'] or '(none)'}")
        print(f"ERROR: {r['error'] or '(none)'}")
        replay = settings.artifacts_dir / r["cortex_task_id"]
        print(f"ARTIFACTS: {replay}")
        ans = ""
        while ans not in ("y", "n", "s"):
            ans = input("pass? [y]es / [n]o / [s]kip: ").strip().lower()
        if ans == "y":
            r["verdict"] = "pass"
        elif ans == "n":
            r["verdict"] = "fail"
    report["summary"] = summarize(report["tasks"])
    path.write_text(json.dumps(report, indent=2))
    print(f"\nUpdated: {path}")
    _print_summary(report)
    return 0


def _print_summary(report: dict) -> None:
    s = report["summary"]
    print(json.dumps(s, indent=2))


def show_report(path: Path) -> int:
    report = json.loads(path.read_text())
    _print_table(report["tasks"])
    _print_summary(report)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Online-Mind2Web benchmark runner")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--level", choices=["easy", "medium", "hard"], default=None)
    p.add_argument("--task", default=None)
    p.add_argument("--tasks-file", type=Path, default=None,
                   help="file with one task_id per line")
    p.add_argument("--max-steps", type=int, default=30)
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--judge", type=Path, default=None)
    p.add_argument("--report", type=Path, default=None)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")

    if args.judge:
        return judge(args.judge)
    if args.report:
        return show_report(args.report)
    if not settings.openai_api_key:
        print("OPENAI_API_KEY not set — benchmark skipped", file=sys.stderr)
        return 2
    asyncio.run(
        run_bench(
            args.level, args.limit, args.task, args.max_steps, args.timeout,
            args.tasks_file,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
