from fastapi.testclient import TestClient

from cortex.main import app
from cortex.vault import credentials


def test_vault_roundtrip():
    from cortex.store import db

    db.init_db()
    session = db.create_session("vault-test")
    credentials.store_credentials(
        session.id, "github.com", {"x_username": "u", "x_password": "sekrit"}
    )
    data = credentials.sensitive_data_for(session.id)
    assert data["github.com"]["x_username"] == "u"
    assert data["github.com"]["x_password"] == "sekrit"
    # Raw DB must not contain plaintext.
    row = db.get_credentials_for_session(session.id)[0]
    assert b"sekrit" not in row.data_encrypted


def test_session_crud_and_credentials():
    with TestClient(app) as client:
        resp = client.post("/sessions", json={"name": "acct-1"})
        assert resp.status_code == 201
        sid = resp.json()["id"]

        dup = client.post("/sessions", json={"name": "acct-1"})
        assert dup.status_code == 409

        cred = client.post(
            f"/sessions/{sid}/credentials",
            json={"domain": "github.com", "fields": {"x_password": "hunter2"}},
        )
        assert cred.status_code == 201

        listed = client.get(f"/sessions/{sid}/credentials")
        assert listed.status_code == 200
        assert listed.json()[0]["domain"] == "github.com"

        delete = client.delete(f"/sessions/{sid}/credentials/github.com")
        assert delete.status_code == 204

        assert client.delete(f"/sessions/{sid}").status_code == 204
        assert client.get(f"/sessions/{sid}").status_code == 404


def test_approvals_empty_and_unknown_respond():
    with TestClient(app) as client:
        resp = client.get("/approvals")
        assert resp.status_code == 200
        missing = client.post("/approvals/nope/respond", json={"approve": True})
        assert missing.status_code == 404


def test_api_key_gate(monkeypatch):
    from cortex.config import settings

    monkeypatch.setattr(settings, "require_api_key", True)
    monkeypatch.setattr(settings, "api_keys", "good-key")
    with TestClient(app) as client:
        assert client.get("/tasks").status_code == 401
        assert client.get("/tasks", headers={"x-api-key": "good-key"}).status_code == 200
        assert client.get("/health").status_code == 200


def test_host_matches():
    from cortex.engine.runner import _host_matches

    assert _host_matches("https://example.com/x", ["example.com"])
    assert _host_matches("https://sub.example.com/", ["example.com"])
    assert not _host_matches("https://evil-example.com/", ["example.com"])
    assert not _host_matches("https://example.com.evil.net/", ["example.com"])
