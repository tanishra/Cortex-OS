from abc import ABC, abstractmethod
from pathlib import Path

from cortex.models import StepRecord


class ArtifactStore(ABC):
    """Per-task step records, screenshots, and replay index."""

    @abstractmethod
    def write_step(
        self, task_id: str, step: StepRecord, screenshot_b64: str | None
    ) -> StepRecord: ...

    @abstractmethod
    def get_replay(self, task_id: str) -> dict | None: ...

    @abstractmethod
    def list_steps(self, task_id: str) -> list[dict]: ...

    @abstractmethod
    def get_screenshot_path(self, task_id: str, filename: str) -> Path | None: ...

    @abstractmethod
    def task_dir(self, task_id: str) -> Path: ...
