"""Crash-resume checkpoint: condense prior run state for a restarted agent.

Honest limit: the new agent does NOT recover byte-identical memory — it gets
the last URL plus a short progress summary. Browser profile (cookies/logins)
persists on disk across restarts.
"""

import json
import logging

from cortex.store import artifacts
from cortex.store.db import TaskRow

logger = logging.getLogger("cortex.checkpoint")

_SUMMARY_STEP_COUNT = 3
_SUMMARY_MAX_CHARS = 1500


async def build_checkpoint(row: TaskRow) -> str:
    """JSON: {last_url, steps_taken, summary} from prior step artifacts."""
    try:
        steps = await artifacts.list_steps(row.id)
    except Exception:
        logger.warning("Task %s: checkpoint read failed", row.id, exc_info=True)
        steps = []

    last_url = row.start_url or ""
    if steps:
        last_url = steps[-1].get("url") or last_url

    bits = []
    for s in steps[-_SUMMARY_STEP_COUNT:]:
        goal = s.get("next_goal") or s.get("evaluation") or ""
        if goal:
            bits.append(f"step {s.get('n')}: {goal}")
    summary = "\n".join(bits)[-_SUMMARY_MAX_CHARS:]

    return json.dumps(
        {"last_url": last_url, "steps_taken": row.steps_taken, "summary": summary}
    )


def resume_task_text(original: str, checkpoint: dict) -> str:
    """Task prompt for a resumed run: original goal + condensed progress."""
    summary = checkpoint.get("summary") or "(no recorded progress)"
    last_url = checkpoint.get("last_url") or "unknown"
    return (
        f"{original}\n\n"
        "--- RESUME CONTEXT ---\n"
        f"You previously worked on this task and were interrupted. "
        f"Progress so far:\n{summary}\n"
        f"Start by navigating to {last_url} — page state may have changed; "
        "re-verify before acting."
    )
