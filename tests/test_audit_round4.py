"""Audit round-4 regression tests: B1–B4, G1–G4, N1/N2/N6."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cortex.engine import runner
from cortex.engine.gates import make_allowlist
from cortex.models import TaskRequest, TaskStatus
from cortex.store import db


def test_allowlist_always_permits_done():
    """B2: an allowlist without 'done' must still let the agent finish."""
    real = AsyncMock(return_value="executed")
    allowed = make_allowlist({"navigate"} | {"done"}, real)
    action = SimpleNamespace(
        model_dump=lambda exclude_unset: {"done": {"text": "finished"}}
    )
    assert asyncio.run(allowed(action)) == "executed"


def test_consume_key_daily_limit_atomic():
    """B4: second consume past the limit fails even sequentially."""
    db.init_db()
    row, _key = db.create_api_key("limited", daily_limit=1)
    assert db.consume_key(row.id) is True
    assert db.consume_key(row.id) is False


def test_consume_key_unlimited():
    db.init_db()
    row, _key = db.create_api_key("unl")
    assert db.consume_key(row.id) and db.consume_key(row.id)


def test_setup_crash_emits_status_event(monkeypatch, tmp_path):
    """N6: setup-phase failure → FAILED + both error and status events."""
    import pathlib

    db.init_db()
    row, _ = db.create_task(TaskRequest(task="setup crash"))

    def _denied(self, mode=0o777, parents=False, exist_ok=False):
        raise PermissionError("denied")

    monkeypatch.setattr(pathlib.Path, "mkdir", _denied)
    asyncio.run(runner.run_task(row.id))
    updated = db.get_task(row.id)
    assert updated.status == TaskStatus.FAILED
    kinds = [e.kind for e in db.list_events(row.id)]
    assert "error" in kinds and "status" in kinds


def test_delete_session_removes_credentials():
    """N1: session delete cascades to its credential rows."""
    db.init_db()
    s = db.create_session("cascade")
    db.upsert_credential(s.id, "x.com", b"enc")
    assert db.get_credentials_for_session(s.id)
    db.delete_session(s.id)
    assert db.get_credentials_for_session(s.id) == []


def test_seed_api_keys_prunes_stale(monkeypatch):
    """N2: env keys removed from API_KEYS get deleted on next seed."""
    db.init_db()
    db.seed_api_keys(["key-a", "key-b"])
    seeded = [k for k in db.list_api_keys() if k.label == "env:seeded"]
    assert len(seeded) == 2
    db.seed_api_keys(["key-a"])
    remaining = [k for k in db.list_api_keys() if k.label == "env:seeded"]
    assert len(remaining) == 1
    assert remaining[0].prefix == "key-a"


def test_queued_task_ids_helper():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="queued task"))
    assert row.id in db.queued_task_ids()
    db.update_task(row.id, status=TaskStatus.DONE)
    assert row.id not in db.queued_task_ids()


def test_timeout_cancel_persists_checkpoint(monkeypatch):
    """G4: CancelledError mid-run still writes a resume checkpoint."""
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="timeout task"))

    class _A:
        def __init__(self, **kwargs):
            self.tools = SimpleNamespace(act=AsyncMock())
            self.token_cost_service = SimpleNamespace(
                get_usage_summary=AsyncMock(
                    return_value=SimpleNamespace(total_tokens=0)
                )
            )

        def pause(self):
            pass

        async def run(self, max_steps=None):
            raise asyncio.CancelledError()

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )
    try:
        asyncio.run(runner.run_task(row.id))
    except asyncio.CancelledError:
        pass
    cp = json.loads(db.get_task(row.id).resume_from)
    assert "last_url" in cp and "prev_status" in cp
    db.update_task(row.id, status=TaskStatus.CANCELLED)  # don't linger active


def test_watcher_resumes_on_flag(monkeypatch):
    """B1: resume_requested flag unpauses the agent via the watcher."""
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="watch me"))
    resumed = []

    class _A:
        def __init__(self, **kwargs):
            self.tools = SimpleNamespace(act=AsyncMock())
            self.token_cost_service = SimpleNamespace(
                get_usage_summary=AsyncMock(
                    return_value=SimpleNamespace(total_tokens=0)
                )
            )

        def pause(self):
            pass

        def resume(self):
            resumed.append(True)

        async def run(self, max_steps=None):
            # Give the watcher a beat, then set the flag externally.
            await asyncio.sleep(0.2)
            db.update_task(row.id, resume_requested=True)
            await asyncio.sleep(2.5)
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
    asyncio.run(runner.run_task(row.id))
    assert resumed
    assert db.get_task(row.id).resume_requested is False
