"""P6b: tool_loop/wandered_domain categories, compare, autojudge."""

import json
from types import SimpleNamespace

from evals.bench import autojudge, classify_failure, compare_reports, summarize


def _ev(kind, url=None, payload=None, actions=None):
    return SimpleNamespace(
        kind=kind, url=url, payload_json=payload,
        actions_json=json.dumps(actions or []),
        tokens_in=None, tokens_out=None, cost_usd=None, duration_ms=None,
    )


def _row(status="failed", error="bench_timeout"):
    return SimpleNamespace(status=status, error=error)


def test_tool_loop():
    """Same action repeated 5+ times consecutively → tool_loop."""
    events = [
        _ev("step", url="https://www.foxsports.com/", actions=["find_elements"])
        for _ in range(6)
    ]
    assert classify_failure(
        _row(), events, "https://www.foxsports.com/"
    ) == "tool_loop"


def test_wandered_domain():
    """Leaving for a non-search domain → wandered_domain."""
    events = [
        _ev("step", url="https://www.adoptapet.com/", actions=["navigate"]),
        _ev("step", url="https://www.petfinder.com/", actions=["navigate"]),
    ]
    assert classify_failure(
        _row(), events, "https://www.adoptapet.com/"
    ) == "wandered_domain"


def test_subdomain_still_same_site():
    events = [_ev("step", url="https://shop.apple.com/us/", actions=["navigate"])]
    assert classify_failure(
        _row(), events, "https://www.apple.com/"
    ) == "timeout_on_site"


def test_search_beats_domain_wander():
    events = [
        _ev("step", url="https://www.petfinder.com/"),
        _ev("step", url="https://www.bing.com/search?q=x"),
    ]
    assert classify_failure(
        _row(), events, "https://www.adoptapet.com/"
    ) == "wandered_offsite"


def test_compare_reports(tmp_path):
    def _report(model, done):
        return {
            "meta": {"model": model},
            "tasks": [],
            "summary": {
                "total": 15, "status_done": done, "status_failed": 15 - done,
                "success_rate": done / 15, "avg_steps": 10, "avg_duration_s": 100,
                "cost_usd_per_task": 0.02, "cost_usd_total": 0.3,
                "failure_categories": {"success": done},
                "passed": done, "failed": 0, "unscored": 0,
            },
        }
    p1 = tmp_path / "r1.json"
    p2 = tmp_path / "r2.json"
    p1.write_text(json.dumps(_report("gpt-5-mini", 5)))
    p2.write_text(json.dumps(_report("gpt-5-nano", 3)))
    rows = compare_reports([p1, p2])
    assert rows[0]["model"] == "gpt-5-mini" and rows[0]["done"] == 5
    assert rows[1]["model"] == "gpt-5-nano" and rows[1]["success_rate"] == 0.2


def test_autojudge(tmp_path):
    report = {
        "meta": {},
        "tasks": [
            {"status": "done", "result": "got it", "verdict": "unscored",
             "steps": 3, "duration_s": 10, "task_id": "a",
             "failure_category": "success"},
            {"status": "failed", "result": None, "verdict": "unscored",
             "steps": 2, "duration_s": 20, "task_id": "b",
             "failure_category": "timeout_on_site"},
        ],
        "summary": {},
    }
    f = tmp_path / "run.json"
    f.write_text(json.dumps(report))
    autojudge(f)
    out = json.loads(f.read_text())
    assert out["tasks"][0]["verdict"] == "pass"
    assert out["tasks"][1]["verdict"] == "fail"
    assert out["summary"]["success_rate"] == 0.5


def test_max_completion_tokens_setting():
    from cortex.config import settings

    assert settings.openai_max_completion_tokens >= 8192


def test_tool_loop_runtime_stop(monkeypatch):
    """5 identical consecutive actions → task FAILED with tool_loop error."""
    import asyncio
    from unittest.mock import AsyncMock

    from cortex.engine import runner
    from cortex.models import TaskRequest, TaskStatus
    from cortex.store import db

    db.init_db()
    row, _ = db.create_task(TaskRequest(task="loop it"))

    step_state = SimpleNamespace(
        url="https://a.com", title="A", dom_state=None, browser_errors=[]
    )
    action = SimpleNamespace(
        model_dump=lambda exclude_unset: {"find_elements": {"s": "x"}}
    )
    out = SimpleNamespace(
        action=[action], evaluation_previous_goal=None, memory=None,
        next_goal="go",
    )

    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self._stop = kwargs["register_should_stop_callback"]
            self.tools = SimpleNamespace(act=AsyncMock())
            self.token_cost_service = SimpleNamespace(
                get_usage_summary=AsyncMock(
                    return_value=SimpleNamespace(total_tokens=0)
                )
            )

        async def run(self, max_steps=None):
            for i in range(1, 6):
                await self._cb(step_state, out, i)
                if await self._stop():
                    break
            return SimpleNamespace(
                usage=None, agent_steps=lambda: [], final_result=lambda: "x",
                is_successful=lambda: False, errors=lambda: [],
            )

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )
    asyncio.run(runner.run_task(row.id))
    updated = db.get_task(row.id)
    assert updated.status == TaskStatus.FAILED
    assert updated.error.startswith("tool_loop")


def test_tool_loop_no_stop_on_varied_actions(monkeypatch):
    """Varied actions must NOT trigger the loop guard."""
    import asyncio
    from unittest.mock import AsyncMock

    from cortex.engine import runner
    from cortex.models import TaskRequest, TaskStatus
    from cortex.store import db

    db.init_db()
    row, _ = db.create_task(TaskRequest(task="varied"))

    step_state = SimpleNamespace(
        url="https://a.com", title="A", dom_state=None, browser_errors=[]
    )
    names = ["click", "input", "click", "navigate", "extract"]

    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self._stop = kwargs["register_should_stop_callback"]
            self.tools = SimpleNamespace(act=AsyncMock())
            self.token_cost_service = SimpleNamespace(
                get_usage_summary=AsyncMock(
                    return_value=SimpleNamespace(total_tokens=0)
                )
            )

        async def run(self, max_steps=None):
            for i, name in enumerate(names, 1):
                out = SimpleNamespace(
                    action=[
                        SimpleNamespace(
                            model_dump=lambda exclude_unset, _n=name: {_n: {}}
                        )
                    ],
                    evaluation_previous_goal=None, memory=None, next_goal="go",
                )
                await self._cb(step_state, out, i)
                if await self._stop():
                    break
            return SimpleNamespace(
                usage=None, agent_steps=lambda: [], final_result=lambda: "ok",
                is_successful=lambda: True, errors=lambda: [],
            )

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )
    asyncio.run(runner.run_task(row.id))
    assert db.get_task(row.id).status == TaskStatus.DONE


def test_summarize_categories_includes_new():
    recs = [
        {"status": "failed", "verdict": "fail", "steps": 1, "duration_s": 1,
         "failure_category": "tool_loop"},
        {"status": "failed", "verdict": "fail", "steps": 1, "duration_s": 1,
         "failure_category": "wandered_domain"},
    ]
    s = summarize(recs)
    assert s["failure_categories"]["tool_loop"] == 1
    assert s["failure_categories"]["wandered_domain"] == 1
