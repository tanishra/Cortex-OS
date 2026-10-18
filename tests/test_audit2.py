import asyncio

from cortex import worker
from cortex.engine import runner
from cortex.models import TaskStatus
from cortex.store import db
from cortex.utils import _BG_TASKS, spawn


def test_spawn_holds_and_discards():
    async def main():
        t = spawn(asyncio.sleep(0))
        assert t in _BG_TASKS
        await t
        await asyncio.sleep(0)

    asyncio.run(main())
    assert not _BG_TASKS


def test_session_startup_does_not_fail_tasks():
    db.init_db()
    row, _ = db.create_task(_req("live task"))
    db.update_task(row.id, status=TaskStatus.RUNNING)

    asyncio.run(worker.session_startup({}))
    assert db.get_task(row.id).status == TaskStatus.RUNNING

    asyncio.run(worker.task_startup({}))
    # P4d: re-queued for checkpoint resume, not failed
    assert db.get_task(row.id).status == TaskStatus.QUEUED


def _req(task, **kw):
    from cortex.models import TaskRequest

    return TaskRequest(task=task, **kw)


def test_detect_wall_helper():
    """_detect_wall surfaces the wall kind; clean pages return None."""
    from types import SimpleNamespace

    state = SimpleNamespace(
        url="https://x.test",
        title="Verify",
        dom_state=SimpleNamespace(
            llm_representation=lambda: "<p>Please complete the captcha</p>"
        ),
    )
    out = SimpleNamespace(evaluation_previous_goal=None, next_goal="solve")
    assert runner._detect_wall("t", state, out) == "captcha_generic"

    clean = SimpleNamespace(
        url="https://x.test",
        title="OK",
        dom_state=SimpleNamespace(llm_representation=lambda: "<p>hello</p>"),
    )
    assert runner._detect_wall("t", clean, out) is None

    broken = SimpleNamespace(
        url="https://x.test",
        title="",
        dom_state=SimpleNamespace(
            llm_representation=lambda: (_ for _ in ()).throw(RuntimeError("x"))
        ),
    )
    assert runner._detect_wall("t", broken, out) is None  # swallow → no wall


def test_open_session_clears_close_flag(monkeypatch):
    db.init_db()
    monkeypatch.setattr(worker.settings, "session_open_timeout_s", 0)
    s = db.create_session("svc")
    db.update_session(s.id, close_requested=True)

    class FakeBrowser:
        async def start(self):
            pass

        async def kill(self):
            pass

        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(worker, "Browser", FakeBrowser)
    asyncio.run(worker.open_session_job({}, s.id))
    # job ran → flag normalized at start; session unlocked at end
    after = db.get_session(s.id)
    assert after.close_requested is False
    assert after.locked_by is None


def test_priority_unknown_defaults_normal():
    from cortex.api.routes_tasks import _PRIORITY_DEFER_MS

    assert _PRIORITY_DEFER_MS.get("bogus") is None
    assert _PRIORITY_DEFER_MS["high"] < 0 < _PRIORITY_DEFER_MS["low"]


def test_running_state_exposed():
    runner._RUNNING["t1"] = {"agent": object(), "state": {"status": "running"}}
    try:
        assert runner.running_agent("t1") is not None
        assert runner.running_state("t1")["status"] == "running"
        assert runner.running_agent("none") is None
        assert runner.running_state("none") is None
    finally:
        runner._RUNNING.clear()
