from fastapi.testclient import TestClient

from cortex.main import app


def test_health():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_create_and_get_task():
    with TestClient(app) as client:
        resp = client.post("/tasks", json={"task": "open example.com and read the heading"})
        assert resp.status_code == 202
        task = resp.json()
        assert task["status"] in ("queued", "running")
        assert task["task"] == "open example.com and read the heading"

        got = client.get(f"/tasks/{task['id']}")
        assert got.status_code == 200
        assert got.json()["id"] == task["id"]


def test_list_tasks():
    with TestClient(app) as client:
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


def test_get_missing_task_404():
    with TestClient(app) as client:
        assert client.get("/tasks/does-not-exist").status_code == 404


def test_cancel_task():
    with TestClient(app) as client:
        resp = client.post("/tasks", json={"task": "a long running browser task"})
        task_id = resp.json()["id"]
        cancelled = client.post(f"/tasks/{task_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] in ("cancelled", "running")


def test_idempotency_key_returns_same_task():
    with TestClient(app) as client:
        body = {"task": "idempotent task", "idempotency_key": "key-123"}
        t1 = client.post("/tasks", json=body).json()
        t2 = client.post("/tasks", json=body).json()
        assert t1["id"] == t2["id"]


def test_replay_404_for_fresh_task():
    with TestClient(app) as client:
        resp = client.post("/tasks", json={"task": "another task for replay test"})
        assert client.get(f"/tasks/{resp.json()['id']}/replay").status_code == 404
