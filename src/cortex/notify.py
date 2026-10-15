"""Human escalation webhook — fire-and-forget notification.

Must never raise: a broken webhook must not kill a task.
"""

import logging

import httpx

from cortex.config import settings

logger = logging.getLogger("cortex.notify")


async def notify_human(task_id: str, url: str, reason: str) -> None:
    """POST a human_required event to HUMAN_NOTIFY_URL. No-op if unset."""
    if not settings.human_notify_url:
        logger.debug("Task %s needs human (%s) but HUMAN_NOTIFY_URL unset", task_id, reason)
        return
    payload = {
        "event": "human_required",
        "task_id": task_id,
        "url": url,
        "reason": reason,
        "action": f"POST /tasks/{task_id}/resume after resolving",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(settings.human_notify_url, json=payload)
            logger.info(
                "Task %s: human_required webhook sent (%s)", task_id, resp.status_code
            )
    except Exception:
        logger.warning(
            "Task %s: human_required webhook failed", task_id, exc_info=True
        )
