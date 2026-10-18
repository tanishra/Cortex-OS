from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from cortex.config import settings
from cortex.main import app
from cortex.ports.queue import JobQueue
from cortex.store import db


def _expired_session(name="old"):
    s = db.create_session(name)
    db.update_session(s.id, expires_at=datetime.now(UTC) - timedelta(hours=1))
    return db.get_session(s.id)


def test_session_gets_expiry_on_create():
    db.init_db()
    s = db.create_session("fresh")
    assert s.expires_at is not None
    assert not db.is_session_expired(s)


def test_expired_session_rejected():
    db.init_db()
    s = _expired_session()
    assert db.is_session_expired(s)

    with TestClient(app) as client:
        resp = client.post(
            "/tasks", json={"task": "expired session task", "session_id": s.id}
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"]

        resp = client.post(f"/sessions/{s.id}/open")
        assert resp.status_code == 410


def test_delete_session_locked_409():
    db.init_db()
    s = db.create_session("locked")
    db.try_lock_session(s.id, "holder")
    with TestClient(app) as client:
        assert client.delete(f"/sessions/{s.id}").status_code == 409
    db.unlock_session(s.id)


def test_delete_profile_flag(tmp_path, monkeypatch):
    db.init_db()
    s = db.create_session("with-profile")
    profile = settings.browser_profiles_dir / s.id
    profile.mkdir(parents=True)
    (profile / "cookie").write_text("x")

    with TestClient(app) as client:
        client.delete(f"/sessions/{s.id}?delete_profile=true")
    assert not profile.exists()


def test_delete_expired_sessions_returns_ids():
    db.init_db()
    alive = db.create_session("alive")
    dead = _expired_session()
    ids = db.delete_expired_sessions()
    assert dead.id in ids
    assert db.get_session(alive.id) is not None


def test_open_session_enqueues_on_sessions_queue():
    db.init_db()
    s = db.create_session("lane-test")

    class Spy(JobQueue):
        def __init__(self):
            self.calls = []

        async def enqueue(self, job, *args, queue_name=None):
            self.calls.append((job, args, queue_name))
            return True

        def available(self):
            return True

        async def queue_depth(self, queue_name=None):
            return None

        async def aclose(self):
            pass

    with TestClient(app) as client:
        spy = Spy()
        app.state.queue = spy
        resp = client.post(f"/sessions/{s.id}/open")
        assert resp.status_code == 202
        assert spy.calls[0][2] == settings.session_queue_name
