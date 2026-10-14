"""Backend registry: kind -> name -> class, resolved via settings.

Kinds: "artifacts", "secrets", "queue". Each has a corresponding
settings field: artifact_backend, secrets_backend, queue_backend.
"""

import logging
from typing import Any, TypeVar

from cortex.config import settings

logger = logging.getLogger("cortex.ports")

T = TypeVar("T")

_KINDS = ("artifacts", "secrets", "queue")

_REGISTRY: dict[str, dict[str, type]] = {k: {} for k in _KINDS}
_INSTANCES: dict[tuple[str, str], Any] = {}


def register(kind: str, name: str):
    """Class decorator: @register("artifacts", "fs")."""
    if kind not in _KINDS:
        raise ValueError(f"unknown backend kind: {kind}")

    def deco(cls: type) -> type:
        _REGISTRY[kind][name] = cls
        return cls

    return deco


def _setting_name(kind: str) -> str:
    return f"{kind}_backend" if kind != "artifacts" else "artifact_backend"


def get_backend(kind: str) -> Any:
    """Return the singleton backend instance for the configured backend name."""
    name = getattr(settings, _setting_name(kind))
    key = (kind, name)
    if key not in _INSTANCES:
        cls = _REGISTRY[kind].get(name)
        if cls is None:
            raise RuntimeError(
                f"no {kind} backend named {name!r}; registered: {sorted(_REGISTRY[kind])}"
            )
        _INSTANCES[key] = cls()
        logger.info("Initialized %s backend: %s", kind, name)
    return _INSTANCES[key]


def reset_registry() -> None:
    """Drop cached instances (tests)."""
    _INSTANCES.clear()
