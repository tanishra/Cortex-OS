"""P4d — durable resume (checkpoint) + orphan browser cleanup."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cortex.engine import checkpoint, orphans, runner
from cortex.models import StepRecord, TaskRequest, TaskStatus
from cortex.store import artifacts, db


def _fake_ok(monkeypatch, captured=None):
    history = SimpleNamespace(
        usage=None,
        agent_steps=lambda: [],
        final_result=lambda: "ok",
        is_successful=lambda: True,
        errors=lambda: [],
    )

    class _A:
        def __init__(self, **kwargs):
            self.task = kwargs["task"]
            self.tools = SimpleNamespace(act=lambda *a, **k: None)
            if captured is not None:
                captured["task"] = kwargs["task"]

        async def run(self, max_steps=None):
            if captured is not None:
                captured["max_steps"] = max_steps
            return history

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )


def test_build_checkpoint_from_artifacts():
    db.init_db()
    row, _ = db.create_task(
        TaskRequest(task="checkpoint", start_url="https://a.com")
    )
    for n in range(1, 4):
        step = StepRecord(
            n=n, url=f"https://a.com/p{n}", title=f"p{n}", next_goal=f"goal {n}"
        )
        asyncio.run(artifacts.write_step(row.id, step, None))

    cp = json.loads(asyncio.run(checkpoint.build_checkpoint(row)))
    assert cp["last_url"] == "https://a.com/p3"
    assert "goal 3" in cp["summary"]


def test_resume_prompt_contains_context(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="resume me"))
    db.update_task(
        row.id,
        status=TaskStatus.RUNNING,
        steps_taken=3,
        resume_from=json.dumps(
            {"last_url": "https://a.com/p2", "steps_taken": 3, "summary": "saw list"}
        ),
    )
    captured = {}
    _fake_ok(monkeypatch, captured)

    asyncio.run(runner.run_task(row.id))
    assert "saw list" in captured["task"]
    assert "https://a.com/p2" in captured["task"]
    # Remaining budget: default max_steps - steps_taken
    assert captured["max_steps"] == 100 - 3
    assert db.get_task(row.id).resume_from is None
    assert db.get_task(row.id).status == TaskStatus.DONE


def test_resume_step_offset_no_clobber(monkeypatch):
    """Resumed run must not overwrite prior step artifacts (step_n restarts
    at 1 inside the agent — we offset by prior steps_taken)."""
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="offset", start_url="https://a.com"))
    step = StepRecord(n=1, url="https://a.com/1", title="one")
    asyncio.run(artifacts.write_step(row.id, step, None))
    db.update_task(
        row.id,
        status=TaskStatus.RUNNING,
        steps_taken=1,
        resume_from='{"last_url": "https://a.com/1", "steps_taken": 1, "summary": "s"}',
    )

    step_state = SimpleNamespace(
        url="https://a.com/2", title="two", dom_state=None, browser_errors=[]
    )
    out = SimpleNamespace(
        action=[], evaluation_previous_goal=None, memory=None, next_goal=None
    )

    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        async def run(self, max_steps=None):
            await self._cb(step_state, out, 1)  # agent counts from 1
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

    steps = asyncio.run(artifacts.list_steps(row.id))
    assert sorted(s["n"] for s in steps) == [1, 2]  # no overwrite
    assert db.get_task(row.id).steps_taken == 2


def test_no_resume_unchanged(monkeypatch):
    db.init_db()
    row, _ = db.create_task(
        TaskRequest(task="fresh", start_url="https://a.com", max_steps=10)
    )
    captured = {}
    _fake_ok(monkeypatch, captured)
    asyncio.run(runner.run_task(row.id))
    assert "RESUME CONTEXT" not in captured["task"]
    assert captured["max_steps"] == 10


def test_resume_reuses_pending_approval(monkeypatch):
    """Resumed task with a pending domain-approval doesn't create a second."""
    db.init_db()
    row, _ = db.create_task(
        TaskRequest(task="gated", approval_domains=["b.example.com"])
    )
    db.create_approval(row.id, "agent entered gated domain", "https://b.example.com")

    step_state = SimpleNamespace(
        url="https://b.example.com", title="B", dom_state=None, browser_errors=[]
    )
    out = SimpleNamespace(
        action=[], evaluation_previous_goal=None, memory=None, next_goal=None
    )

    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        def pause(self):
            pass

        def resume(self):
            pass

        async def run(self, max_steps=None):
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
    asyncio.run(runner.run_task(row.id))
    approvals = db.list_approvals(status="pending", task_id=row.id)
    assert len(approvals) == 1  # reused, not duplicated


def test_kill_orphan_browsers(monkeypatch, tmp_path):
    procs = [
        (123, str(tmp_path / "live")),
        (456, str(tmp_path / "dead")),
    ]
    monkeypatch.setattr(orphans, "_chromium_procs", lambda root: procs)
    killed = []
    monkeypatch.setattr(orphans.os, "kill", lambda pid, sig: killed.append(pid))
    n = orphans.kill_orphan_browsers(tmp_path, {"live"})
    assert n == 1
    assert killed == [456]


def test_chromium_procs_parse(monkeypatch, tmp_path):
    fake_out = (
        f"999 /Chromium --user-data-dir={tmp_path}/abc --headless\n"
        "888 /other-app --flag\n"
    )
    monkeypatch.setattr(
        orphans.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=fake_out),
    )
    procs = orphans._chromium_procs(tmp_path)
    assert procs == [(999, f"{tmp_path}/abc")]
