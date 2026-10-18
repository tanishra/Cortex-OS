"""P4c — backpressure + per-domain rate limit."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from cortex.config import settings
from cortex.engine import limits, runner
from cortex.main import app
from cortex.models import TaskRequest, TaskStatus
from cortex.ports.queue import JobQueue
from cortex.store import db


class _FakeRedis:
    def __init__(self, now=None):
        self.store = {}
        self.now = now or time.time()

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class _FakeQueue(JobQueue):
    def __init__(self, depth):
        self._depth = depth

    async def enqueue(self, job, *args, **kwargs):
        return True

    async def queue_depth(self, queue_name=None):
        return self._depth

    def available(self):
        return True

    async def aclose(self):
        pass


def test_429_when_queue_deep(monkeypatch):
    monkeypatch.setattr(settings, "max_queued_tasks", 5)
    with TestClient(app) as client:
        app.state.queue = _FakeQueue(depth=5)
        resp = client.post("/tasks", json={"task": "backpressure me"})
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == str(settings.backpressure_retry_after_s)


def test_accepted_below_depth(monkeypatch):
    monkeypatch.setattr(settings, "max_queued_tasks", 5)
    with TestClient(app) as client:
        app.state.queue = _FakeQueue(depth=2)
        resp = client.post("/tasks", json={"task": "fine"})
        assert resp.status_code == 202


def test_accepted_when_depth_unknown(monkeypatch):
    monkeypatch.setattr(settings, "max_queued_tasks", 0)
    with TestClient(app) as client:
        app.state.queue = _FakeQueue(depth=None)
        resp = client.post("/tasks", json={"task": "redis down"})
        assert resp.status_code == 202


def test_domain_wait_first_call_no_wait():
    redis = _FakeRedis()
    waited = asyncio.run(limits.domain_wait(redis, "example.com", 10))
    assert waited == 0.0
    assert "cortex:rate:example.com" in redis.store


def test_domain_wait_within_interval(monkeypatch):
    now = time.time()
    redis = _FakeRedis(now=now)
    redis.store["cortex:rate:example.com"] = str(now - 3)  # started 3s ago
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    waited = asyncio.run(limits.domain_wait(redis, "example.com", 10))
    assert slept == [pytest.approx(7, abs=0.5)]
    assert waited == pytest.approx(7, abs=0.5)


def test_domain_wait_disabled_and_no_host():
    redis = _FakeRedis()
    assert asyncio.run(limits.domain_wait(redis, "example.com", 0)) == 0.0
    assert asyncio.run(limits.domain_wait(redis, "", 10)) == 0.0
    assert redis.store == {}


def test_events_limit_bounded():
    from cortex.store import db

    db.init_db()
    row, _ = db.create_task(TaskRequest(task="limit check"))
    with TestClient(app) as client:
        assert client.get(f"/tasks/{row.id}/events", params={"limit": 99999}).status_code == 422
        assert client.get(f"/tasks/{row.id}/events", params={"limit": 5}).status_code == 200


def test_domain_wait_redis_failure_tolerated():
    class _Broken:
        async def get(self, key):
            raise ConnectionError("down")

    assert asyncio.run(limits.domain_wait(_Broken(), "x.com", 10)) == 0.0


def test_runner_calls_throttle(monkeypatch):
    """run_task invokes domain_wait when rate limiting is on."""
    db.init_db()
    row, _ = db.create_task(
        TaskRequest(task="throttle task", start_url="https://example.com")
    )
    monkeypatch.setattr(settings, "rate_limit_per_domain_s", 5)
    calls = []

    async def fake_domain_wait(redis, host, interval):
        calls.append((host, interval))
        return 0.0

    monkeypatch.setattr(runner, "domain_wait", fake_domain_wait)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock()))
    monkeypatch.setattr(runner, "Agent", lambda **k: SimpleNamespace(
        tools=SimpleNamespace(act=lambda *a, **k: None),
        run=AsyncMock(return_value=SimpleNamespace(
            usage=None,
            agent_steps=lambda: [],
            final_result=lambda: "ok",
            is_successful=lambda: True,
            errors=lambda: [],
        )),
    ))

    asyncio.run(runner.run_task(row.id, redis=_FakeRedis()))
    assert calls == [("example.com", 5)]
    assert db.get_task(row.id).status == TaskStatus.DONE
