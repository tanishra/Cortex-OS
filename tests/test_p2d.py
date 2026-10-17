from fastapi.testclient import TestClient

from cortex.auth import KEY_PREFIX, generate_key, hash_key
from cortex.config import settings
from cortex.main import app
from cortex.store import db


def test_hash_and_generate_key():
    assert hash_key("abc") == hash_key("abc")
    assert hash_key("abc") != hash_key("abd")
    key = generate_key()
    assert key.startswith(KEY_PREFIX)
    assert generate_key() != key  # entropy


def test_seed_env_keys_idempotent():
    db.init_db()
    n1 = db.seed_api_keys(["k-one", "k-two"])
    n2 = db.seed_api_keys(["k-one", "k-two", "k-three"])
    assert n1 == 2 and n2 == 1
    prefixes = {k.prefix for k in db.list_api_keys()}
    assert {"k-one", "k-two", "k-three"} <= prefixes


def test_auth_flow_and_quota(monkeypatch):
    db.init_db()
    monkeypatch.setattr(settings, "require_api_key", True)
    monkeypatch.setattr(settings, "api_keys", "seed-key")

    row, plain = db.create_api_key("limited", daily_limit=2)

    with TestClient(app) as client:
        # seeded env key works
        assert client.get("/tasks", headers={"x-api-key": "seed-key"}).status_code == 200
        # bad key rejected
        assert client.get("/tasks", headers={"x-api-key": "bogus"}).status_code == 401
        # created key works, then hits quota
        assert (
            client.get("/tasks", headers={"x-api-key": plain}).status_code == 200
        )
        assert (
            client.get("/tasks", headers={"x-api-key": plain}).status_code == 200
        )
        assert (
            client.get("/tasks", headers={"x-api-key": plain}).status_code == 429
        )


def test_disabled_key_rejected(monkeypatch):
    db.init_db()
    monkeypatch.setattr(settings, "require_api_key", True)
    row, plain = db.create_api_key("revoked")
    db.disable_api_key(row.id)
    with TestClient(app) as client:
        assert client.get("/tasks", headers={"x-api-key": plain}).status_code == 401


def test_admin_routes_hide_secrets(monkeypatch):
    db.init_db()
    monkeypatch.setattr(settings, "require_api_key", True)
    _, master = db.create_api_key("master")
    headers = {"x-api-key": master}

    with TestClient(app) as client:
        resp = client.post(
            "/admin/keys", json={"label": "svc"}, headers=headers
        )
        assert resp.status_code == 201
        new_key = resp.json()["key"]
        assert new_key.startswith("ctx_")

        listing = client.get("/admin/keys", headers=headers).json()
        assert all("key" not in k and "key_hash" not in k for k in listing)
        assert any(k["label"] == "svc" for k in listing)

        # revoke → 401 for that key
        kid = next(k["id"] for k in listing if k["label"] == "svc")
        assert client.delete(f"/admin/keys/{kid}", headers=headers).status_code == 204
        assert (
            client.get("/tasks", headers={"x-api-key": new_key}).status_code == 401
        )
