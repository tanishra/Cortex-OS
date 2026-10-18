"""P4 audit round 2 — retry artifact offset, retry events, checkpoint persist."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arq.worker import Retry

from cortex.engine import runner
from cortex.models import TaskRequest, TaskStatus
from cortex.store import artifacts, db
from cortex.worker import run_task_job


def _install_agent(monkeypatch, step_url="https://a.com", crash=None):
    step_state = SimpleNamespace(
        url=step_url, title="A", dom_state=None, browser_errors=[]
    )
    out = SimpleNamespace(
        action=[], evaluation_previous_goal=None, memory=None,
        next_goal="next thing",
    )

    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        def pause(self):
            pass

        async def run(self, max_steps=None):
            if crash is not None:
                # Emit a step first so artifacts/checkpoint data exist.
                await self._cb(step_state, out, 1)
                raise crash
            await self._cb(step_state, out, 1)
            return SimpleNamespace(
                usage=None,
                agent_steps=lambda: [1],
                final_result=lambda: "ok",
                is_successful=lambda: True,
                errors=lambda: [],
            )

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )


def test_retry_does_not_clobber_step_artifacts(monkeypatch):
    """Attempt 2's steps continue numbering — attempt 1 evidence preserved."""
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="retry me cleanly"))

    _install_agent(monkeypatch, crash=RuntimeError("connection reset"))
    with pytest.raises(Retry):
        asyncio.run(run_task_job({"job_try": 1}, row.id))
    assert db.get_task(row.id).steps_taken == 1

    # Attempt 2 succeeds — agent counts n from 1 again internally.
    _install_agent(monkeypatch, step_url="https://b.com")
    asyncio.run(run_task_job({"job_try": 2}, row.id))

    steps = asyncio.run(artifacts.list_steps(row.id))
    assert sorted(s["n"] for s in steps) == [1, 2]
    assert steps[0]["url"] == "https://a.com"  # attempt-1 evidence intact
    assert db.get_task(row.id).steps_taken == 2
    assert db.get_task(row.id).status == TaskStatus.DONE


def test_retry_emits_status_events(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="see my retries"))
    _install_agent(monkeypatch, crash=RuntimeError("connection refused"))

    with pytest.raises(Retry):
        asyncio.run(run_task_job({"job_try": 1}, row.id))

    statuses = [
        json.loads(e.payload_json)
        for e in db.list_events(row.id)
        if e.kind == "status"
    ]
    assert {"to": "queued", "reason": "retry", "attempt": 1} in statuses


def test_dead_letter_emits_event(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="last chance"))
    _install_agent(monkeypatch, crash=RuntimeError("connection refused"))

    from cortex.config import settings

    asyncio.run(run_task_job({"job_try": settings.task_max_retries}, row.id))
    statuses = [
        json.loads(e.payload_json)
        for e in db.list_events(row.id)
        if e.kind == "status"
    ]
    assert any(
        s.get("reason") == "dead_letter" and s.get("to") == "failed"
        for s in statuses
    )


def test_transient_crash_writes_checkpoint(monkeypatch):
    """After a transient crash, resume_from is repopulated — retry resumes warm."""
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="crash mid-flight"))
    _install_agent(
        monkeypatch, step_url="https://mid.com", crash=RuntimeError("timeout: nav")
    )

    with pytest.raises(Retry):
        asyncio.run(run_task_job({"job_try": 1}, row.id))

    updated = db.get_task(row.id)
    cp = json.loads(updated.resume_from)
    assert cp["last_url"] == "https://mid.com"
    assert cp["steps_taken"] == 1
    assert "next thing" in cp["summary"]
