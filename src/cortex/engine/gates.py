"""Action-level approval gates: wraps tools.act to pause gated actions.

browser-use funnels every action through Tools.act() before execution —
wrapping that method gives a true pre-action gate without forking.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from browser_use.agent.views import ActionResult

from cortex.models import TaskStatus
from cortex.notify import notify_human
from cortex.store import db

logger = logging.getLogger("cortex.gates")

_DETAILS_LIMIT = 4096
_POLL_S = 1.0


def make_action_gate(
    task_id: str, gated_names: set[str], original_act: Callable, get_url: Callable[[], str]
) -> Callable:
    """Return an act() replacement that gates actions in gated_names."""

    def _action_entries(action: Any) -> list[tuple[str, Any]]:
        try:
            return [
                (k, v)
                for k, v in action.model_dump(exclude_unset=True).items()
                if v is not None
            ]
        except Exception:
            return []

    async def gated_act(*args: Any, **kwargs: Any) -> ActionResult:
        action = kwargs.get("action", args[0] if args else None)
        for name, params in _action_entries(action):
            if name not in gated_names:
                continue
            details = json.dumps({"action": name, "params": params}, default=str)[
                :_DETAILS_LIMIT
            ]
            # Reuse an existing pending approval (step timeouts can retry actions).
            approval = await db.arun(db.pending_approval_for_task, task_id)
            if approval is None:
                approval = await db.arun(
                    db.create_approval,
                    task_id,
                    f"gated action: {name}",
                    get_url(),
                    details,
                )
                await db.arun(
                    db.update_task, task_id, status=TaskStatus.WAITING_APPROVAL
                )
                logger.info(
                    "Task %s: action %s gated, approval %s created",
                    task_id,
                    name,
                    approval.id,
                )
                asyncio.create_task(
                    notify_human(task_id, get_url(), f"approval_action:{name}")
                )

            # Wait for resolution; cancel flag is an escape hatch.
            while True:
                status = await db.arun(db.get_approval_status, approval.id)
                if status == "approved":
                    await db.arun(
                        db.update_task, task_id, status=TaskStatus.RUNNING
                    )
                    break
                if status == "denied" or await db.arun(
                    db.is_cancel_requested, task_id
                ):
                    return ActionResult(
                        success=False,
                        error=f"action '{name}' denied by human",
                        long_term_memory=(
                            f"Human denied the gated action '{name}'. "
                            "Do not retry it; adjust the plan."
                        ),
                    )
                await asyncio.sleep(_POLL_S)

        return await original_act(*args, **kwargs)

    return gated_act
