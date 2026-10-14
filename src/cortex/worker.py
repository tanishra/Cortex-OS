"""arq worker entrypoint: consumes task jobs and runs the browser agent."""

import asyncio
import logging

from arq.connections import RedisSettings

from cortex.config import settings
from cortex.engine.runner import run_task
from cortex.logging import setup_logging
from cortex.store.db import init_db

setup_logging()
logger = logging.getLogger("cortex.worker")


async def run_task_job(ctx: dict, task_id: str) -> None:
    logger.info("Worker picked up task %s", task_id)
    try:
        await asyncio.wait_for(run_task(task_id), timeout=settings.task_timeout_s)
    except TimeoutError:
        logger.error("Task %s exceeded timeout of %ds", task_id, settings.task_timeout_s)
        from cortex.models import TaskStatus
        from cortex.store import db

        db.update_task(
            task_id,
            status=TaskStatus.FAILED,
            error=f"timeout: exceeded {settings.task_timeout_s}s",
        )


async def startup(ctx: dict) -> None:
    init_db()
    logger.info("Worker started, concurrency=%d", settings.worker_concurrency)


class WorkerSettings:
    functions = [run_task_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_concurrency
    job_timeout = settings.task_timeout_s + 60
    max_tries = 1
