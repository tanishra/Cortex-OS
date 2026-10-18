"""P4b — retry policy + dead-letter."""

import asyncio
from types import SimpleNamespace

import pytest
from arq.worker import Retry

from cortex.config import settings
from cortex.engine import runner
from cortex.engine.retry import classify
from cortex.models import TaskRequest, TaskStatus
from cortex.store import db
from cortex.worker import run_task_job


def test_classify_transient():
    assert classify("TimeoutError: navigation timed out") == "transient"
    assert classify(RuntimeError("RateLimitError: 429")) == "transient"
    assert classify("APIConnectionError: connection reset") == "transient"
    assert classify("TargetClosedError: browser crashed") == "transient"


def test_classify_permanent():
    assert classify("domain_blocked: agent navigated outside allowed_domains") == "permanent"
    assert classify("session_expired: session TTL elapsed") == "permanent"
    assert classify("cancelled by user") == "permanent"
    assert classify("ValueError: something odd") == "permanent"


def _ctx(job_try=1):
    return {"job_try": job_try}


def _fake_agent_ok(monkeypatch):
    history = SimpleNamespace(
        usage=None,
        agent_steps=lambda: [],
        final_result=lambda: "ok",
        is_successful=lambda: True,
        errors=lambda: [],
    )

    class _A:
        def __init__(self, **kwargs):
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        async def run(self, max_steps=None):
            return history

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())

    class _B:
        def __init__(self, **kwargs):
            pass

        async def kill(self):
            pass

    monkeypatch.setattr(runner, "Browser", _B)


def _fake_agent_crash(monkeypatch, exc):
    class _A:
        def __init__(self, **kwargs):
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        async def run(self, max_steps=None):
            raise exc

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())

    class _B:
        def __init__(self, **kwargs):
            pass

        async def kill(self):
            pass

    monkeypatch.setattr(runner, "Browser", _B)


def test_transient_retries_via_arq(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="retry me"))
    _fake_agent_crash(monkeypatch, RuntimeError("RateLimitError: 429"))

    with pytest.raises(Retry) as ei:
        asyncio.run(run_task_job(_ctx(1), row.id))

    assert ei.value.defer_score > 0 or getattr(ei.value, "defer", None)
    updated = db.get_task(row.id)
    assert updated.status == TaskStatus.QUEUED
    assert updated.retry_count == 1
    assert "retrying" in (updated.error or "")


def test_dead_letter_after_max_tries(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="die quietly"))
    _fake_agent_crash(monkeypatch, RuntimeError("connection refused"))

    # Last allowed attempt — no Retry, permanent dead-letter.
    asyncio.run(run_task_job(_ctx(settings.task_max_retries), row.id))

    updated = db.get_task(row.id)
    assert updated.status == TaskStatus.FAILED
    assert (updated.error or "").startswith("dead_letter:")
    assert updated.retry_count == settings.task_max_retries


def test_permanent_fails_no_retry(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="permanent fail"))
    _fake_agent_crash(monkeypatch, ValueError("weird bug"))

    asyncio.run(run_task_job(_ctx(1), row.id))
    updated = db.get_task(row.id)
    assert updated.status == TaskStatus.FAILED
    assert "dead_letter" not in (updated.error or "")


def test_cancelled_task_early_out(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="cancelled before retry"))
    db.request_cancel(row.id)
    db.update_task(row.id, status=TaskStatus.CANCELLED)
    called = []
    monkeypatch.setattr(runner, "Agent", lambda **k: called.append(1))

    asyncio.run(run_task_job(_ctx(1), row.id))
    assert called == []
    assert db.get_task(row.id).status == TaskStatus.CANCELLED


def test_happy_path_unchanged(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="normal task"))
    _fake_agent_ok(monkeypatch)
    asyncio.run(run_task_job(_ctx(1), row.id))
    assert db.get_task(row.id).status == TaskStatus.DONE
