from abc import ABC, abstractmethod

from cortex.store.db import CredentialRow


class SecretsStore(ABC):
    """Session-scoped credential storage. Values must never reach the LLM."""

    @abstractmethod
    def store(self, session_id: str, domain: str, fields: dict[str, str]) -> CredentialRow: ...

    @abstractmethod
    def resolve(self, session_id: str) -> dict[str, dict[str, str]]:
        """{domain: {placeholder: value}} for browser-use sensitive_data."""

    @abstractmethod
    def list(self, session_id: str) -> list[CredentialRow]: ...

    @abstractmethod
    def delete(self, session_id: str, domain: str) -> bool: ...
