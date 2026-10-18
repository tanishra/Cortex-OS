"""P5a — action allowlist, token cost guard, fallback model, latency flag."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cortex.config import settings
from cortex.engine import runner
from cortex.engine.gates import make_allowlist
from cortex.models import TaskRequest, TaskStatus
from cortex.store import db


def _ok_history():
    return SimpleNamespace(
        usage=None,
        agent_steps=lambda: [],
        final_result=lambda: "ok",
        is_successful=lambda: True,
        errors=lambda: [],
    )


def _patch_base(monkeypatch, captured=None):
    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self._stop = kwargs["register_should_stop_callback"]
            self.tools = SimpleNamespace(act=AsyncMock())
            self.token_cost_service = SimpleNamespace(
                get_usage_summary=AsyncMock(
                    return_value=SimpleNamespace(total_tokens=999_999)
                )
            )
            if captured is not None:
                captured["kwargs"] = kwargs

        def pause(self):
            pass

        async def run(self, max_steps=None):
            await self._stop()  # drives cost/cancel checks like browser-use does
            return _ok_history()

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )
    return _A


def test_allowlist_blocks_disallowed():
    """ActionResult error + real act never invoked."""
    allowed = make_allowlist({"navigate"}, AsyncMock())
    action = SimpleNamespace(
        model_dump=lambda exclude_unset: {"click_element_by_index": {"index": 1}}
    )
    result = asyncio.run(allowed(action))
    assert result.success is False
    assert "not in allowed_actions" in result.error


def test_allowlist_passes_allowed():
    real = AsyncMock(return_value="executed")
    allowed = make_allowlist({"navigate"}, real)
    action = SimpleNamespace(
        model_dump=lambda exclude_unset: {"navigate": {"url": "https://x.com"}}
    )
    assert asyncio.run(allowed(action)) == "executed"
    real.assert_awaited_once()


def test_allowlist_wired_in_runner(monkeypatch):
    db.init_db()
    row, _ = db.create_task(
        TaskRequest(task="read only", allowed_actions=["navigate", "extract"])
    )
    called = []

    class _Act:
        async def real(self, *a, **k):
            called.append(True)
            return "ok"

    class _A:
        def __init__(self, **kwargs):
            self.tools = SimpleNamespace(act=_Act().real)
            self.token_cost_service = SimpleNamespace(
                get_usage_summary=AsyncMock(
                    return_value=SimpleNamespace(total_tokens=0)
                )
            )

        async def run(self, max_steps=None):
            blocked = await self.tools.act(
                SimpleNamespace(
                    model_dump=lambda exclude_unset: {"input_text": {"text": "x"}}
                )
            )
            assert blocked.success is False
            ok = await self.tools.act(
                SimpleNamespace(
                    model_dump=lambda exclude_unset: {"navigate": {"url": "https://x.com"}}
                )
            )
            assert ok == "ok"
            return _ok_history()

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )
    asyncio.run(runner.run_task(row.id))
    assert called  # navigate reached real act
    assert db.get_task(row.id).status == TaskStatus.DONE


def test_cost_guard_stops_task(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="expensive", max_tokens=10))
    _patch_base(monkeypatch)
    asyncio.run(runner.run_task(row.id))
    updated = db.get_task(row.id)
    assert updated.status == TaskStatus.FAILED
    assert updated.error.startswith("cost_exceeded")


def test_cost_guard_off_by_default(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="no budget"))
    _patch_base(monkeypatch)
    asyncio.run(runner.run_task(row.id))
    assert db.get_task(row.id).status == TaskStatus.DONE


def test_fallback_llm_passed(monkeypatch):
    db.init_db()
    captured = {}
    _patch_base(monkeypatch, captured)
    monkeypatch.setattr(settings, "openai_fallback_model", "gpt-4o-mini")
    row, _ = db.create_task(TaskRequest(task="fallback"))
    asyncio.run(runner.run_task(row.id))
    assert captured["kwargs"]["fallback_llm"] is not None


def test_no_fallback_llm_by_default(monkeypatch):
    db.init_db()
    captured = {}
    _patch_base(monkeypatch, captured)
    row, _ = db.create_task(TaskRequest(task="no fallback"))
    asyncio.run(runner.run_task(row.id))
    assert captured["kwargs"]["fallback_llm"] is None


def test_latency_flag_emitted(monkeypatch):
    db.init_db()
    monkeypatch.setattr(settings, "task_latency_budget_s", 0.001)
    row, _ = db.create_task(TaskRequest(task="slow"))

    step_state = SimpleNamespace(
        url="https://a.com", title="A", dom_state=None, browser_errors=[]
    )
    out = SimpleNamespace(
        action=[], evaluation_previous_goal=None, memory=None, next_goal="go"
    )

    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self.tools = SimpleNamespace(act=lambda *a, **k: None)
            self.token_cost_service = SimpleNamespace(
                get_usage_summary=AsyncMock(
                    return_value=SimpleNamespace(total_tokens=0)
                )
            )

        async def run(self, max_steps=None):
            await self._cb(step_state, out, 1)
            return _ok_history()

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )
    asyncio.run(runner.run_task(row.id))
    kinds = [e.kind for e in db.list_events(row.id)]
    assert "latency_exceeded" in kinds
    assert db.get_task(row.id).status == TaskStatus.DONE
    settings.task_latency_budget_s = 0.0  # restore
