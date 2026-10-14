import base64
import json
import logging
from pathlib import Path

from cortex.config import settings
from cortex.models import StepRecord
from cortex.ports.artifacts import ArtifactStore
from cortex.ports.registry import get_backend, register

logger = logging.getLogger("cortex.artifacts")


@register("artifacts", "fs")
class FsArtifactStore(ArtifactStore):
    """Filesystem artifact store: artifacts/<task_id>/step_NNNN.{json,png}."""

    def task_dir(self, task_id: str) -> Path:
        d = settings.artifacts_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_step(
        self, task_id: str, step: StepRecord, screenshot_b64: str | None
    ) -> StepRecord:
        d = self.task_dir(task_id)
        if screenshot_b64:
            png_path = d / f"step_{step.n:04d}.png"
            try:
                png_path.write_bytes(base64.b64decode(screenshot_b64))
                step.screenshot = png_path.name
            except Exception:
                logger.exception(
                    "Failed to write screenshot for task %s step %d", task_id, step.n
                )
        (d / f"step_{step.n:04d}.json").write_text(step.model_dump_json(indent=2))
        self._update_replay_index(task_id, step)
        return step

    def _update_replay_index(self, task_id: str, step: StepRecord) -> None:
        index_path = self.task_dir(task_id) / "replay.json"
        index = {"steps": []}
        if index_path.exists():
            index = json.loads(index_path.read_text())
        index["steps"].append(step.model_dump(mode="json"))
        index_path.write_text(json.dumps(index, indent=2))

    def get_replay(self, task_id: str) -> dict | None:
        index_path = self.task_dir(task_id) / "replay.json"
        if not index_path.exists():
            return None
        return json.loads(index_path.read_text())

    def list_steps(self, task_id: str) -> list[dict]:
        return [
            json.loads(p.read_text())
            for p in sorted(self.task_dir(task_id).glob("step_*.json"))
        ]

    def get_screenshot_path(self, task_id: str, filename: str) -> Path | None:
        if "/" in filename or ".." in filename:
            return None
        p = self.task_dir(task_id) / filename
        return p if p.exists() and p.suffix == ".png" else None


def _store() -> ArtifactStore:
    return get_backend("artifacts")


def write_step(task_id: str, step: StepRecord, screenshot_b64: str | None) -> StepRecord:
    return _store().write_step(task_id, step, screenshot_b64)


def get_replay(task_id: str) -> dict | None:
    return _store().get_replay(task_id)


def list_steps(task_id: str) -> list[dict]:
    return _store().list_steps(task_id)


def get_screenshot_path(task_id: str, filename: str) -> Path | None:
    return _store().get_screenshot_path(task_id, filename)


def task_dir(task_id: str) -> Path:
    return _store().task_dir(task_id)
