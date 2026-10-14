from abc import ABC, abstractmethod
from typing import Any


class JobQueue(ABC):
    """Async job queue connecting API and worker processes."""

    @abstractmethod
    async def enqueue(self, job: str, *args: Any) -> bool:
        """Enqueue a named job for the worker. False if queue unavailable."""

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    async def aclose(self) -> None: ...
