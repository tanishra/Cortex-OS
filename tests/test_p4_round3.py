"""P4 audit round 3 — corrupt checkpoint, worker events, wall re-notify."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cortex.engine import runner
from cortex.models import TaskRequest, TaskStatus
from cortex.store import db
from cortex.worker import approval_response_job, human_resume_job


def _ok_agent(monkeypatch):
    class _A:
        def __init__(self, **kwargs):
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        async def run(self, max_steps=None):
            return SimpleNamespace(
                usage=None,
                agent_steps=lambda: [],
                final_result=lambda: "ok",
                is_successful=lambda: True,
                errors=lambda: [],
            )

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )


def test_corrupt_resume_from_fresh_start(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="corrupt checkpoint"))
    db.update_task(row.id, status=TaskStatus.RUNNING, resume_from="}{not json")
    _ok_agent(monkeypatch)
    asyncio.run(runner.run_task(row.id))
    updated = db.get_task(row.id)
    assert updated.status == TaskStatus.DONE
    assert updated.resume_from is None


def test_session_expired_emits_event(monkeypatch):
    db.init_db()
    from datetime import timedelta

    from cortex.models import utcnow

    s = db.create_session("expired")
    db.update_session(s.id, expires_at=utcnow() - timedelta(seconds=1))
    row, _ = db.create_task(TaskRequest(task="expired sess", session_id=s.id))
    _ok_agent(monkeypatch)
    asyncio.run(runner.run_task(row.id))
    assert db.get_task(row.id).status == TaskStatus.FAILED
    statuses = [
        json.loads(e.payload_json)
        for e in db.list_events(row.id)
        if e.kind == "status"
    ]
    assert {"to": "failed", "reason": "session_expired"} in statuses


def test_approval_jobs_emit_events():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="approve me"))

    class _Agent:
        def __init__(self):
            self.resumed = False
            self.stopped = False

        def resume(self):
            self.resumed = True

        def stop(self):
            self.stopped = True

    agent = _Agent()
    runner._RUNNING[row.id] = {"agent": agent, "state": {"status": "waiting_approval"}}
    asyncio.run(approval_response_job({}, row.id, True))
    assert agent.resumed
    statuses = [
        json.loads(e.payload_json)
        for e in db.list_events(row.id)
        if e.kind == "status"
    ]
    assert {"to": "running", "reason": "approved"} in statuses
    runner._RUNNING.pop(row.id, None)


def test_human_resume_emits_event():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="human wall"))
    db.update_task(row.id, status=TaskStatus.WAITING_HUMAN)

    class _Agent:
        def resume(self):
            pass

    runner._RUNNING[row.id] = {"agent": _Agent(), "state": {"status": "waiting_human"}}
    asyncio.run(human_resume_job({}, row.id))
    statuses = [
        json.loads(e.payload_json)
        for e in db.list_events(row.id)
        if e.kind == "status"
    ]
    assert {"to": "running", "reason": "human_resumed"} in statuses
    runner._RUNNING.pop(row.id, None)


def test_wall_renotify_suppressed_after_resume(monkeypatch):
    """Resumed-from-waiting_human: first wall re-detection pauses silently."""
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="wall again"))
    db.update_task(
        row.id,
        status=TaskStatus.RUNNING,
        resume_from=json.dumps(
            {
                "last_url": "https://wall.com",
                "steps_taken": 0,
                "summary": "hit wall",
                "prev_status": "waiting_human",
            }
        ),
    )
    notified = []
    monkeypatch.setattr(
        runner, "spawn", lambda coro: notified.append(coro) or coro.close()
    )

    wall_state = SimpleNamespace(
        url="https://wall.com",
        title="",
        dom_state=None,
        browser_errors=[],
    )
    out = SimpleNamespace(
        action=[],
        evaluation_previous_goal="verify you are human",
        memory=None,
        next_goal="solve captcha",
    )
    monkeypatch.setattr(runner, "_detect_wall", lambda *a: "captcha_generic")

    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        def pause(self):
            pass

        async def run(self, max_steps=None):
            await self._cb(wall_state, out, 1)
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
    asyncio.run(runner.run_task(row.id))
    assert notified == []
    assert db.get_task(row.id).status in (
        TaskStatus.DONE,
        TaskStatus.WAITING_HUMAN,
    )
