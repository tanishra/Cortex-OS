import base64
import json
import logging
from pathlib import Path

from cortex.config import settings
from cortex.models import StepRecord
from cortex.ports.artifacts import ArtifactStore
from cortex.ports.registry import get_backend, register

logger = logging.getLogger("cortex.artifacts")


def safe_filename(filename: str) -> str | None:
    """Reject traversal; return the name if it looks like a plain file name."""
    if "/" in filename or ".." in filename or "\\" in filename:
        return None
    return filename


@register("artifacts", "fs")
class FsArtifactStore(ArtifactStore):
    """Filesystem artifact store: artifacts/<task_id>/step_NNNN.{json,png}."""

    def task_dir(self, task_id: str) -> Path:
        d = settings.artifacts_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def write_step(
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

    async def get_replay(self, task_id: str) -> dict | None:
        index_path = settings.artifacts_dir / task_id / "replay.json"
        if not index_path.exists():
            return None
        return json.loads(index_path.read_text())

    async def list_steps(self, task_id: str) -> list[dict]:
        d = settings.artifacts_dir / task_id
        return [
            json.loads(p.read_text())
            for p in sorted(d.glob("step_*.json"))
        ]

    async def get_screenshot(self, task_id: str, filename: str) -> bytes | None:
        if safe_filename(filename) is None:
            return None
        p = settings.artifacts_dir / task_id / filename
        if not p.exists() or p.suffix != ".png":
            return None
        return p.read_bytes()

    async def delete_task(self, task_id: str) -> None:
        import shutil

        shutil.rmtree(settings.artifacts_dir / task_id, ignore_errors=True)


def _store() -> ArtifactStore:
    return get_backend("artifacts")


async def write_step(
    task_id: str, step: StepRecord, screenshot_b64: str | None
) -> StepRecord:
    return await _store().write_step(task_id, step, screenshot_b64)


async def get_replay(task_id: str) -> dict | None:
    return await _store().get_replay(task_id)


async def list_steps(task_id: str) -> list[dict]:
    return await _store().list_steps(task_id)


async def get_screenshot(task_id: str, filename: str) -> bytes | None:
    return await _store().get_screenshot(task_id, filename)


async def delete_task(task_id: str) -> None:
    await _store().delete_task(task_id)
