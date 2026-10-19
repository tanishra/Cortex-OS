"""P6a: benchmark runner — dry tests (no live calls)."""

import json
from unittest.mock import patch

import pytest

from evals import bench


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


ROWS = [
    {
        "task_id": "t1",
        "confirmed_task": "do a",
        "website": "https://a.com/",
        "reference_length": 3,
        "level": "easy",
    },
    {
        "task_id": "t2",
        "confirmed_task": "do b",
        "website": "https://b.com/",
        "reference_length": 7,
        "level": "medium",
    },
    {
        "task_id": "t3",
        "confirmed_task": "do c",
        "website": "https://c.com/",
        "reference_length": 4,
        "level": "easy",
    },
]


def test_load_benchmark_tasks_filters_and_limits(tmp_path):
    f = tmp_path / "t.jsonl"
    _write_jsonl(f, ROWS)
    assert len(bench.load_benchmark_tasks(f)) == 3
    easy = bench.load_benchmark_tasks(f, level="easy")
    assert [t["task_id"] for t in easy] == ["t1", "t3"]
    assert len(bench.load_benchmark_tasks(f, level="easy", limit=1)) == 1


def test_load_benchmark_tasks_validation(tmp_path):
    f = tmp_path / "bad.jsonl"
    f.write_text(json.dumps({"task_id": "x"}) + "\n")
    with pytest.raises(ValueError, match="missing fields"):
        bench.load_benchmark_tasks(f)


def test_summarize_counts_and_averages():
    recs = [
        {"status": "done", "verdict": "pass", "steps": 4, "duration_s": 10,
         "tokens_in": 100, "tokens_out": 20, "cost_usd": 0.01},
        {"status": "failed", "verdict": "fail", "steps": 2, "duration_s": 5,
         "tokens_in": 50, "tokens_out": 10, "cost_usd": 0.005},
        {"status": "done", "verdict": "unscored", "steps": 6, "duration_s": 15,
         "tokens_in": None, "tokens_out": None, "cost_usd": None},
    ]
    s = bench.summarize(recs)
    assert s["total"] == 3 and s["passed"] == 1 and s["failed"] == 1
    assert s["unscored"] == 1 and s["success_rate"] == 0.5
    assert s["avg_steps"] == 4 and s["avg_duration_s"] == 10
    assert s["tokens_in_total"] == 150 and s["cost_usd_total"] == 0.015
    assert s["cost_usd_per_task"] == 0.005


def test_summarize_all_unscored_rate_none():
    s = bench.summarize([{"status": "done", "verdict": "unscored", "steps": 1,
                         "duration_s": 1}])
    assert s["success_rate"] is None


def test_judge_writes_verdicts(tmp_path):
    report = {
        "meta": {},
        "tasks": [
            {"task_id": "t1", "status": "done", "steps": 3, "task": "x",
             "result": "y", "error": "", "verdict": "unscored",
             "cortex_task_id": "c1", "website": "https://a.com/",
             "level": "easy", "tokens_in": 1, "tokens_out": 1,
             "cost_usd": 0.01, "duration_s": 5},
            {"task_id": "t2", "status": "failed", "steps": 1, "task": "z",
             "result": None, "error": "boom", "verdict": "pass",  # already scored
             "cortex_task_id": "c2", "website": "https://b.com/",
             "level": "easy", "tokens_in": None, "tokens_out": None,
             "cost_usd": None, "duration_s": 2},
        ],
        "summary": {},
    }
    f = tmp_path / "run.json"
    f.write_text(json.dumps(report))
    with patch("builtins.input", return_value="n"):
        bench.judge(f)
    out = json.loads(f.read_text())
    assert out["tasks"][0]["verdict"] == "fail"
    assert out["tasks"][1]["verdict"] == "pass"  # untouched
    assert out["summary"]["success_rate"] == 0.5


def test_real_jsonl_loads():
    tasks = bench.load_benchmark_tasks(bench.TASKS_FILE)
    assert len(tasks) >= 250
    assert all(t["confirmed_task"] and t["website"] for t in tasks)
    levels = {t["level"] for t in tasks}
    assert levels == {"easy", "medium", "hard"}
