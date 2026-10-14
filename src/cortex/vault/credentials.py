"""Credential vault: encrypted secret storage per browser session.

Secrets are stored Fernet-encrypted and handed to browser-use via its
`sensitive_data` parameter — the model only ever sees placeholder names,
never raw values.
"""

import json
import logging

from cryptography.fernet import Fernet

from cortex.config import settings
from cortex.store import db

logger = logging.getLogger("cortex.vault")


def _fernet() -> Fernet:
    if not settings.vault_fernet_key:
        raise RuntimeError("VAULT_FERNET_KEY is not configured")
    return Fernet(settings.vault_fernet_key.encode())


def store_credentials(session_id: str, domain: str, fields: dict[str, str]):
    """Encrypt and persist credential fields for a session + domain."""
    payload = json.dumps(fields).encode()
    return db.upsert_credential(session_id, domain, _fernet().encrypt(payload))


def get_credentials(session_id: str) -> dict[str, dict[str, str]]:
    """Return {domain: {placeholder: value}} for a session (decrypted)."""
    out: dict[str, dict[str, str]] = {}
    for row in db.get_credentials_for_session(session_id):
        try:
            out[row.domain] = json.loads(_fernet().decrypt(row.data_encrypted))
        except Exception:
            logger.exception("Failed to decrypt credential %s", row.id)
    return out


def sensitive_data_for(session_id: str) -> dict[str, dict[str, str]]:
    """browser-use `sensitive_data` payload: domain-scoped placeholder map."""
    return get_credentials(session_id)


def delete_credentials(session_id: str, domain: str) -> bool:
    return db.delete_credential(session_id, domain)
