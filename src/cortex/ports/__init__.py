"""Ports: abstract interfaces + registry for swappable backends.

Backends are selected via settings (artifact_backend, secrets_backend,
queue_backend) and resolved lazily through `get_backend`.
"""

from cortex.ports.registry import get_backend, register

__all__ = ["get_backend", "register"]
