"""Flight-recorder UI serving tests."""

from fastapi.testclient import TestClient

from cortex.main import app


def test_ui_index_served():
    r = TestClient(app).get("/ui/")
    assert r.status_code == 200
    assert "CORTEX-OS" in r.text


def test_ui_assets_served():
    c = TestClient(app)
    assert c.get("/ui/styles.css").status_code == 200
    assert c.get("/ui/app.js").status_code == 200


def test_ui_is_public_but_api_still_gated(monkeypatch):
    from cortex.config import settings

    monkeypatch.setattr(settings, "require_api_key", True)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/ui/").status_code == 200
    assert c.get("/ui/app.js").status_code == 200
    assert c.get("/tasks").status_code == 401
