from fastapi.testclient import TestClient

from cortex.main import app
from cortex.ports.queue import JobQueue
from cortex.store import db


class _SpyQueue(JobQueue):
    def __init__(self):
        self.calls = []

    async def enqueue(self, job, *args, queue_name=None, defer_ms=None):
        self.calls.append((job, args, queue_name, defer_ms))
        return True

    def available(self):
        return True

    async def aclose(self):
        pass


def _post(client, body):
    return client.post("/tasks", json=body)


def test_priority_roundtrip():
    db.init_db()
    with TestClient(app) as client:
        app.state.queue = _SpyQueue()
        hi = _post(client, {"task": "urgent task", "priority": "high"}).json()
        lo = _post(client, {"task": "batch task", "priority": "low"}).json()
        default = _post(client, {"task": "plain task"}).json()

    assert hi["priority"] == "high"
    assert lo["priority"] == "low"
    assert default["priority"] == "normal"


def test_priority_maps_to_defer_ms():
    db.init_db()
    with TestClient(app) as client:
        spy = _SpyQueue()
        app.state.queue = spy
        _post(client, {"task": "task a", "priority": "high"})
        _post(client, {"task": "task b"})
        _post(client, {"task": "task c", "priority": "low"})

    defers = [c[3] for c in spy.calls]
    assert defers == [-3_600_000, None, 60_000]


def test_priority_invalid_rejected():
    with TestClient(app) as client:
        resp = _post(client, {"task": "task x", "priority": "urgent"})
        assert resp.status_code == 422
