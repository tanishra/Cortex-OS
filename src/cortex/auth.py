"""API key hashing/generation. Only sha256 digests are stored."""

import hashlib
import secrets

KEY_PREFIX = "ctx_"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> str:
    """'ctx_' + urlsafe token — identifiable prefix, ~192 bits entropy."""
    return KEY_PREFIX + secrets.token_urlsafe(24)
