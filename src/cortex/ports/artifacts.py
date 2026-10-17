from abc import ABC, abstractmethod

from cortex.models import StepRecord


class ArtifactStore(ABC):
    """Per-task step records, screenshots, and replay index. Async port."""

    @abstractmethod
    async def write_step(
        self, task_id: str, step: StepRecord, screenshot_b64: str | None
    ) -> StepRecord: ...

    @abstractmethod
    async def get_replay(self, task_id: str) -> dict | None: ...

    @abstractmethod
    async def list_steps(self, task_id: str) -> list[dict]: ...

    @abstractmethod
    async def get_screenshot(self, task_id: str, filename: str) -> bytes | None: ...

    @abstractmethod
    async def delete_task(self, task_id: str) -> None: ...
