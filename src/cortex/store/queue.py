"""Queue backend: arq over Redis, with a null fallback when Redis is down."""

import logging
from datetime import timedelta
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from cortex.config import settings
from cortex.ports.queue import JobQueue
from cortex.ports.registry import register

logger = logging.getLogger("cortex.queue")


class NullJobQueue(JobQueue):
    """Used when the queue cannot connect: enqueue() is a no-op, available()=False."""

    async def enqueue(
        self,
        job: str,
        *args: Any,
        queue_name: str | None = None,
        defer_ms: int | None = None,
    ) -> bool:
        logger.warning("Queue unavailable; dropped job %s%r", job, args)
        return False

    def available(self) -> bool:
        return False

    async def queue_depth(self, queue_name: str | None = None) -> int | None:
        return None

    async def aclose(self) -> None:
        pass


@register("queue", "arq")
class ArqJobQueue(JobQueue):
    """arq Redis pool. Call connect() once at app startup."""

    def __init__(self) -> None:
        self._pool: ArqRedis | None = None

    async def connect(self) -> None:
        try:
            self._pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            logger.info("Connected to Redis at %s", settings.redis_url)
        except Exception:
            logger.warning("Redis unavailable — tasks will be created but not enqueued")
            self._pool = None

    async def enqueue(
        self,
        job: str,
        *args: Any,
        queue_name: str | None = None,
        defer_ms: int | None = None,
    ) -> bool:
        if self._pool is None:
            logger.warning("Queue unavailable; dropped job %s%r", job, args)
            return False
        kwargs: dict[str, Any] = {"_queue_name": queue_name}
        if defer_ms is not None:
            kwargs["_defer_by"] = timedelta(milliseconds=defer_ms)
        await self._pool.enqueue_job(job, *args, **kwargs)
        return True

    async def queue_depth(self, queue_name: str | None = None) -> int | None:
        if self._pool is None:
            return None
        from arq.constants import default_queue_name

        return await self._pool.zcard(queue_name or default_queue_name)

    def available(self) -> bool:
        return self._pool is not None

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
