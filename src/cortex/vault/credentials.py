"""Credential vault: encrypted secret storage per browser session.

Secrets are stored Fernet-encrypted and handed to browser-use via its
`sensitive_data` parameter — the model only ever sees placeholder names,
never raw values.
"""

import json
import logging

from cryptography.fernet import Fernet

from cortex.config import settings
from cortex.ports.registry import get_backend, register
from cortex.ports.secrets import SecretsStore
from cortex.store import db
from cortex.store.db import CredentialRow

logger = logging.getLogger("cortex.vault")


def _fernet() -> Fernet:
    if not settings.vault_fernet_key:
        raise RuntimeError("VAULT_FERNET_KEY is not configured")
    return Fernet(settings.vault_fernet_key.encode())


@register("secrets", "fernet")
class FernetSecretsStore(SecretsStore):
    """Fernet-encrypted credentials persisted in the task database."""

    def store(self, session_id: str, domain: str, fields: dict[str, str]) -> CredentialRow:
        payload = json.dumps(fields).encode()
        return db.upsert_credential(session_id, domain, _fernet().encrypt(payload))

    def resolve(self, session_id: str) -> dict[str, dict[str, str]]:
        """{domain: {placeholder: value}} — browser-use `sensitive_data` shape."""
        out: dict[str, dict[str, str]] = {}
        for row in db.get_credentials_for_session(session_id):
            try:
                out[row.domain] = json.loads(_fernet().decrypt(row.data_encrypted))
            except Exception:
                logger.exception("Failed to decrypt credential %s", row.id)
        return out

    def list(self, session_id: str) -> list[CredentialRow]:
        return db.get_credentials_for_session(session_id)

    def delete(self, session_id: str, domain: str) -> bool:
        return db.delete_credential(session_id, domain)


def _store() -> SecretsStore:
    return get_backend("secrets")


def store_credentials(session_id: str, domain: str, fields: dict[str, str]):
    """Encrypt and persist credential fields for a session + domain."""
    return _store().store(session_id, domain, fields)


def get_credentials(session_id: str) -> dict[str, dict[str, str]]:
    """Return {domain: {placeholder: value}} for a session (decrypted)."""
    return _store().resolve(session_id)


def sensitive_data_for(session_id: str) -> dict[str, dict[str, str]]:
    """browser-use `sensitive_data` payload: domain-scoped placeholder map."""
    return _store().resolve(session_id)


def delete_credentials(session_id: str, domain: str) -> bool:
    return _store().delete(session_id, domain)
