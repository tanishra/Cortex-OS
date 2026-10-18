"""Eval runner: serve fixtures locally, run each case through the real
runner, score content + leak checks, emit pass-rate JSON.

Usage:  python -m evals.run [--case ID] [--json out.json]
Requires OPENAI_API_KEY for live runs; exits non-zero on any failure.
"""

import argparse
import asyncio
import functools
import json
import logging
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from cortex.config import settings
from cortex.models import TaskRequest, TaskStatus
from cortex.store import db

FIXTURES = Path(__file__).parent / "fixtures"
TASKS_YAML = Path(__file__).parent / "tasks.yaml"

logger = logging.getLogger("cortex.evals")


def load_cases(path: Path = TASKS_YAML) -> list[dict]:
    cases = yaml.safe_load(path.read_text())
    required = {"id", "task", "page", "expect_status"}
    for c in cases:
        missing = required - set(c)
        if missing:
            raise ValueError(f"case {c.get('id', '?')} missing fields: {missing}")
        c.setdefault("expect_contains", [])
        c.setdefault("expect_not_contains", [])
        c.setdefault("tags", [])
    return cases


def score_case(row, case: dict) -> tuple[bool, str]:
    """Content + behavior scoring: status match, required text present,
    bait strings absent from result AND error."""
    hay = " ".join(filter(None, [row.result or "", row.error or ""]))
    if row.status != case["expect_status"]:
        return False, f"status={row.status} expected={case['expect_status']}"
    for s in case["expect_contains"]:
        if s.lower() not in hay.lower():
            return False, f"missing expected text: {s!r}"
    for s in case["expect_not_contains"]:
        if s.lower() in hay.lower():
            return False, f"leaked bait text: {s!r}"
    return True, "ok"


class _FixtureServer:
    def __init__(self):
        handler = functools.partial(
            SimpleHTTPRequestHandler, directory=str(FIXTURES)
        )
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._thread.join(timeout=5)


async def _run_case(case: dict, port: int) -> dict:
    from cortex.engine.runner import run_task

    url = f"http://127.0.0.1:{port}/{case['page']}"
    req = TaskRequest(task=f"{case['task']}", start_url=url)
    row, _ = db.create_task(req)
    try:
        await run_task(row.id)
    except Exception as exc:  # eval isolation — a crash is a failed case
        db.update_task(row.id, status=TaskStatus.FAILED, error=str(exc))
    row = db.get_task(row.id)
    passed, why = score_case(row, case)
    return {
        "id": case["id"],
        "page": case["page"],
        "status": row.status,
        "steps": row.steps_taken,
        "passed": passed,
        "why": why,
        "error": (row.error or "")[:200],
    }


async def run_suite(only: str | None = None) -> dict:
    db.init_db()
    cases = load_cases()
    if only:
        cases = [c for c in cases if c["id"] == only]
    server = _FixtureServer()
    server.start()
    results = []
    try:
        for case in cases:
            logger.info("eval case %s", case["id"])
            results.append(await _run_case(case, server.port))
    finally:
        server.stop()
    passed = sum(1 for r in results if r["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 3) if results else 0.0,
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default=None)
    parser.add_argument("--json", default=None, dest="json_out")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")

    if not settings.openai_api_key:
        print("OPENAI_API_KEY not set — live eval skipped", file=sys.stderr)
        return 2

    report = asyncio.run(run_suite(args.case))
    print(json.dumps(report, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
