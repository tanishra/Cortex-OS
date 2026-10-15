import asyncio

from fastapi.testclient import TestClient

from cortex.engine.escalation import detect_human_wall
from cortex.main import app
from cortex.models import TaskRequest, TaskStatus
from cortex.ports.queue import JobQueue
from cortex.store import db


def test_detect_captcha_signatures():
    assert detect_human_wall("", "", "cf-challenge-widget") == "cloudflare_challenge"
    assert detect_human_wall("", "Security Check", "") == "security_checkpoint"
    assert detect_human_wall("", "", '<div class="g-recaptcha">') == "recaptcha"
    assert detect_human_wall("https://x.com/login", "", "enter the code we sent") == "otp"
    assert detect_human_wall("", "", "two-factor authentication required") == "two_factor"


def test_detect_clean_page_returns_none():
    text = "Example Domain\nThis domain is for use in documentation examples"
    assert detect_human_wall("https://example.com/", "Example Domain", text) is None


def test_detect_is_case_insensitive():
    assert detect_human_wall("", "", "PLEASE VERIFY YOU ARE HUMAN") == "human_verify"


class _FakeQueue(JobQueue):
    def __init__(self):
        self.jobs = []

    async def enqueue(self, job, *args):
        self.jobs.append((job, args))
        return True

    def available(self):
        return True

    async def aclose(self):
        pass


def test_resume_endpoint_409_and_enqueue():
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="queued task"))
    with TestClient(app) as client:
        app.state.queue = _FakeQueue()
        assert client.post("/tasks/nope/resume").status_code == 404
        # queued task → 409
        assert client.post(f"/tasks/{row.id}/resume").status_code == 409
        # waiting_human → enqueues resume job
        db.update_task(row.id, status=TaskStatus.WAITING_HUMAN)
        resp = client.post(f"/tasks/{row.id}/resume")
        assert resp.status_code == 200
        assert app.state.queue.jobs == [("human_resume_job", (row.id,))]


def test_notify_human_no_url_noop(caplog):
    from cortex.config import settings
    from cortex.notify import notify_human

    settings.human_notify_url = ""
    asyncio.run(notify_human("t1", "https://x.com", "captcha"))  # must not raise


def test_notify_human_posts_payload(monkeypatch):
    from cortex import notify
    from cortex.config import settings

    calls = {}

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json):
            calls["url"] = url
            calls["json"] = json
            return type("R", (), {"status_code": 200})()

    monkeypatch.setattr(settings, "human_notify_url", "https://hook.example.com/x")
    monkeypatch.setattr(notify.httpx, "AsyncClient", FakeClient)
    asyncio.run(notify.notify_human("t2", "https://site.com", "otp"))
    assert calls["url"] == "https://hook.example.com/x"
    assert calls["json"]["event"] == "human_required"
    assert calls["json"]["reason"] == "otp"


def test_notify_human_swallows_errors(monkeypatch):
    from cortex import notify
    from cortex.config import settings

    class BadClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json):
            raise ConnectionError("down")

    monkeypatch.setattr(settings, "human_notify_url", "https://hook.example.com/x")
    monkeypatch.setattr(notify.httpx, "AsyncClient", BadClient)
    asyncio.run(notify.notify_human("t3", "https://site.com", "captcha"))
    settings.human_notify_url = ""
