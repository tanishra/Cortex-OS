"""P4a — task events + stats endpoint."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cortex.engine import runner
from cortex.main import app
from cortex.models import TaskRequest, TaskStatus
from cortex.ports.queue import JobQueue
from cortex.store import db


def test_record_and_list_events():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="events test"))
    db.record_event(row.id, "status", payload_json='{"to": "running"}')
    db.record_event(row.id, "step", n=1, url="https://a.com", duration_ms=120)
    db.record_event(row.id, "step", n=2, url="https://b.com", duration_ms=90)
    db.record_event(row.id, "finished", tokens_in=100, tokens_out=20, cost_usd=0.001)

    events = db.list_events(row.id)
    assert [e.kind for e in events] == ["status", "step", "step", "finished"]
    assert events[1].n == 1
    assert events[3].tokens_in == 100


def test_events_endpoint():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="api events"))
    db.record_event(row.id, "step", n=1, url="https://x.com", actions_json='["click"]')
    with TestClient(app) as client:
        resp = client.get(f"/tasks/{row.id}/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["kind"] == "step"
        assert body[0]["actions"] == ["click"]
        assert client.get("/tasks/nonexistent/events").status_code == 404


def test_stats_endpoint_shape():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="stats task"))
    db.update_task(row.id, status=TaskStatus.DONE, steps_taken=3)
    db.record_event(row.id, "finished", tokens_in=10, tokens_out=5, cost_usd=0.0002)
    with TestClient(app) as client:
        body = client.get("/stats").json()
    assert body["tasks_total"] >= 1
    assert "done" in body["by_status"]
    assert body["success_rate"] >= 0
    assert body["tokens_in_total"] >= 10


def test_stats_queue_depth_null_safe():
    class _NoQueue(JobQueue):
        async def enqueue(self, job, *args, **kwargs):
            return False

        async def queue_depth(self, queue_name=None):
            return None

        def available(self):
            return False

        async def aclose(self):
            pass

    with TestClient(app) as client:
        app.state.queue = _NoQueue()
        body = client.get("/stats").json()
        assert body["queue_depth"] is None


class _FakeHistory:
    usage = SimpleNamespace(
        total_prompt_tokens=111, total_completion_tokens=22,
        total_prompt_cost=0.001, total_completion_cost=0.0001,
    )

    def agent_steps(self):
        return [1, 2]

    def final_result(self):
        return "ok"

    def is_successful(self):
        return True

    def errors(self):
        return []


def test_runner_emits_events(monkeypatch):
    """Fake agent → run_task records status + step + finished events."""
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="emit events"))

    class _FakeAgent:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        def pause(self):
            pass

        async def run(self, max_steps=None):
            state = SimpleNamespace(
                url="https://a.com", title="A", dom_state=None, browser_errors=[]
            )
            out = SimpleNamespace(
                action=[], evaluation_previous_goal=None, memory=None, next_goal=None
            )
            await self._cb(state, out, 1)
            return _FakeHistory()

    monkeypatch.setattr(runner, "Agent", _FakeAgent)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())

    class _FakeBrowser:
        def __init__(self, **kwargs):
            pass

        async def kill(self):
            pass

    monkeypatch.setattr(runner, "Browser", _FakeBrowser)

    import asyncio

    asyncio.run(runner.run_task(row.id))

    events = db.list_events(row.id)
    kinds = [e.kind for e in events]
    assert "step" in kinds
    assert "finished" in kinds
    assert "status" in kinds
    finished = next(e for e in events if e.kind == "finished")
    assert finished.tokens_in == 111
    assert finished.cost_usd == pytest.approx(0.0011)
    step = next(e for e in events if e.kind == "step")
    assert step.duration_ms is not None
    assert step.url == "https://a.com"
    assert db.get_task(row.id).status == TaskStatus.DONE


def test_event_failure_does_not_crash_runner(monkeypatch):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="telemetry resilience"))

    monkeypatch.setattr(db, "record_event", lambda *a, **k: 1 / 0)

    class _FakeAgent:
        def __init__(self, **kwargs):
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        async def run(self, max_steps=None):
            return _FakeHistory()

    monkeypatch.setattr(runner, "Agent", _FakeAgent)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner,
        "Browser",
        lambda **k: SimpleNamespace(kill=lambda: asyncio_sleep()),
    )
    import asyncio

    async def asyncio_sleep():
        pass

    asyncio.run(runner.run_task(row.id))
    assert db.get_task(row.id).status == TaskStatus.DONE
