from abc import ABC, abstractmethod
from typing import Any


class JobQueue(ABC):
    """Async job queue connecting API and worker processes."""

    @abstractmethod
    async def enqueue(
        self,
        job: str,
        *args: Any,
        queue_name: str | None = None,
        defer_ms: int | None = None,
    ) -> bool:
        """Enqueue a named job for the worker. False if queue unavailable."""

    @abstractmethod
    async def queue_depth(self, queue_name: str | None = None) -> int | None:
        """Pending jobs in the named queue (default: main). None if unknown."""

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    async def aclose(self) -> None: ...
