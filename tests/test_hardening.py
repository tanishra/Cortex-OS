import logging
import sys

import pytest

from cortex.logging import JsonFormatter
from cortex.models import TaskRequest
from cortex.ports.registry import get_backend
from cortex.store import db


def test_json_formatter_includes_traceback():
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "n", logging.ERROR, "p", 1, "msg", (), sys.exc_info()
        )
    assert "boom" in formatter.format(record)


def test_update_task_rejects_unknown_field():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="task x"))
    with pytest.raises(ValueError, match="unknown fields"):
        db.update_task(row.id, bogus_field=1)


def test_session_lock_mutual_exclusion():
    db.init_db()
    s = db.create_session("lock-test")
    assert db.try_lock_session(s.id, "owner-a") is True
    assert db.try_lock_session(s.id, "owner-b") is False
    db.unlock_session(s.id)
    assert db.try_lock_session(s.id, "owner-b") is True


def test_approval_dedup_per_task():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="task y"))
    db.create_approval(row.id, "gated", "https://a.example.com")
    assert db.pending_approval_for_task(row.id) is not None
    # Second step on a different URL of the same task must not create another.
    assert db.pending_approval_for_task(row.id).reason == "gated"


def test_has_denied_approval():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="task z"))
    a = db.create_approval(row.id, "gated", "https://b.example.com")
    assert db.has_denied_approval(row.id) is False
    db.resolve_approval(a.id, "denied")
    assert db.has_denied_approval(row.id) is True


def test_requeue_stale_tasks():
    db.init_db()
    t1, _ = db.create_task(TaskRequest(task="stale1"))
    t2, _ = db.create_task(TaskRequest(task="stale2"))
    t3, _ = db.create_task(TaskRequest(task="not-stale"))
    db.update_task(t1.id, status="running")
    db.update_task(t2.id, status="waiting_approval")
    ids = db.requeue_stale_tasks(max_resumes=4)
    assert sorted(ids) == sorted([t1.id, t2.id])
    assert db.get_task(t1.id).status == "queued"
    assert db.get_task(t2.id).resume_count == 1
    assert db.get_task(t3.id).status == "queued"
    # Resume budget exhausted → dead-letter instead of requeue.
    db.update_task(t1.id, status="running", resume_count=4)
    assert db.requeue_stale_tasks(max_resumes=4) == []
    assert db.get_task(t1.id).status == "failed"
    assert "dead_letter" in db.get_task(t1.id).error


def test_idempotency_unique_constraint():
    db.init_db()
    r1, c1 = db.create_task(TaskRequest(task="dup", idempotency_key="dupkey"))
    r2, c2 = db.create_task(TaskRequest(task="dup", idempotency_key="dupkey"))
    assert c1 is True and c2 is False
    assert r1.id == r2.id


def test_registry_returns_singleton_and_rejects_unknown():
    store = get_backend("artifacts")
    assert get_backend("artifacts") is store
    from cortex.config import settings

    original = settings.artifact_backend
    try:
        settings.artifact_backend = "nonexistent"
        with pytest.raises(RuntimeError, match="no artifacts backend"):
            get_backend("artifacts")
    finally:
        settings.artifact_backend = original


def test_open_session_timeout(monkeypatch):
    """Session browser loop exits at the timeout deadline."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from cortex import worker
    from cortex.config import settings

    db.init_db()
    s = db.create_session("timeout-test")

    fake_browser = MagicMock()
    fake_browser.start = AsyncMock()
    fake_browser.kill = AsyncMock()
    monkeypatch.setattr(worker, "Browser", lambda **kw: fake_browser)
    monkeypatch.setattr(settings, "session_open_timeout_s", 0)

    asyncio.run(worker.open_session_job({}, s.id))
    fake_browser.start.assert_awaited_once()
    fake_browser.kill.assert_awaited_once()
    # Lock released afterwards.
    assert db.get_session(s.id).locked_by is None
