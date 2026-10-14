import base64
import json
import logging
from pathlib import Path

from cortex.config import settings
from cortex.models import StepRecord

logger = logging.getLogger("cortex.artifacts")


def task_dir(task_id: str) -> Path:
    d = settings.artifacts_dir / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_step(task_id: str, step: StepRecord, screenshot_b64: str | None) -> StepRecord:
    d = task_dir(task_id)
    if screenshot_b64:
        png_path = d / f"step_{step.n:04d}.png"
        try:
            png_path.write_bytes(base64.b64decode(screenshot_b64))
            step.screenshot = png_path.name
        except Exception:
            logger.exception("Failed to write screenshot for task %s step %d", task_id, step.n)
    (d / f"step_{step.n:04d}.json").write_text(step.model_dump_json(indent=2))
    _update_replay_index(task_id, step)
    return step


def _update_replay_index(task_id: str, step: StepRecord) -> None:
    d = task_dir(task_id)
    index_path = d / "replay.json"
    index = {"steps": []}
    if index_path.exists():
        index = json.loads(index_path.read_text())
    index["steps"].append(step.model_dump(mode="json"))
    index_path.write_text(json.dumps(index, indent=2))


def get_replay(task_id: str) -> dict | None:
    index_path = task_dir(task_id) / "replay.json"
    if not index_path.exists():
        return None
    return json.loads(index_path.read_text())


def list_steps(task_id: str) -> list[dict]:
    d = task_dir(task_id)
    steps = []
    for p in sorted(d.glob("step_*.json")):
        steps.append(json.loads(p.read_text()))
    return steps


def get_screenshot_path(task_id: str, filename: str) -> Path | None:
    if "/" in filename or ".." in filename:
        return None
    p = task_dir(task_id) / filename
    return p if p.exists() and p.suffix == ".png" else None
