import asyncio
import logging

logger = logging.getLogger("cortex.utils")

_BG_TASKS: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """Fire-and-forget a coroutine with a strong reference until completion."""
    t = asyncio.create_task(coro)
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)
    return t
