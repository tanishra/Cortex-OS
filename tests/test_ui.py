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


def test_ui_tape_panel_present():
    html = TestClient(app).get("/ui/").text
    assert 'id="tape"' in html
    assert 'id="tapeScrub"' in html


def test_app_js_has_tape_logic():
    js = TestClient(app).get("/ui/app.js").text
    assert "updateTape" in js and "loadImage" in js and "scrubLock" in js


def test_ops_page_served():
    html = TestClient(app).get("/ui/ops.html").text
    assert "ops-main" in html and 'id="statBand"' in html


def test_ops_js_served():
    js = TestClient(app).get("/ui/ops.js").text
    assert "/stats" in js and "refresh" in js


def test_ui_is_public_but_api_still_gated(monkeypatch):
    from cortex.config import settings

    monkeypatch.setattr(settings, "require_api_key", True)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/ui/").status_code == 200
    assert c.get("/ui/app.js").status_code == 200
    assert c.get("/tasks").status_code == 401
