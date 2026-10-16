"""arq worker entrypoint: consumes task jobs and runs the browser agent."""

import asyncio
import logging
import shutil
import time
from datetime import UTC, datetime, timedelta

from arq import cron
from arq.connections import RedisSettings
from browser_use import Browser, BrowserProfile

from cortex.config import settings
from cortex.engine.runner import run_task, running_agent
from cortex.logging import setup_logging
from cortex.models import TaskStatus
from cortex.store import db
from cortex.store.db import init_db

setup_logging()
logger = logging.getLogger("cortex.worker")


async def run_task_job(ctx: dict, task_id: str) -> None:
    logger.info("Worker picked up task %s", task_id)
    try:
        await asyncio.wait_for(run_task(task_id), timeout=settings.task_timeout_s)
    except TimeoutError:
        logger.error("Task %s exceeded timeout of %ds", task_id, settings.task_timeout_s)
        await db.arun(
            db.update_task,
            task_id,
            status=TaskStatus.FAILED,
            error=f"timeout: exceeded {settings.task_timeout_s}s",
        )


async def approval_response_job(ctx: dict, task_id: str, approve: bool) -> None:
    """Deliver an approve/deny decision to a paused agent in this worker."""
    agent = running_agent(task_id)
    if not agent:
        logger.warning("No running agent for task %s; decision ignored", task_id)
        return
    if approve:
        await db.arun(db.update_task, task_id, status=TaskStatus.RUNNING)
        agent.resume()
        logger.info("Task %s approved, resumed", task_id)
    else:
        agent.stop()
        logger.info("Task %s denied, stopping", task_id)


async def human_resume_job(ctx: dict, task_id: str) -> None:
    """Resume a task paused in waiting_human after the human intervened."""
    task = await db.arun(db.get_task, task_id)
    agent = running_agent(task_id)
    if not task or task.status != TaskStatus.WAITING_HUMAN:
        logger.info("Resume ignored: task %s not waiting_human", task_id)
        return
    if not agent:
        logger.warning("No running agent for task %s; marking failed", task_id)
        await db.arun(
            db.update_task,
            task_id,
            status=TaskStatus.FAILED,
            error="agent_unavailable: worker no longer holds the paused agent",
        )
        return
    await db.arun(db.update_task, task_id, status=TaskStatus.RUNNING)
    agent.resume()
    logger.info("Task %s resumed by human", task_id)


async def open_session_job(ctx: dict, session_id: str) -> None:
    """Hold a headed browser open on a session profile for manual login.

    Closes when POST /sessions/{id}/close sets close_requested, or after
    session_open_timeout_s. The session profile is locked while held.
    """
    session = await db.arun(db.get_session, session_id)
    if not session:
        return
    if not await db.arun(db.try_lock_session, session_id, f"open:{session_id}"):
        logger.warning("Session %s profile already in use; open rejected", session_id)
        return

    profile_dir = settings.browser_profiles_dir / session_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    browser = Browser(
        browser_profile=BrowserProfile(headless=False, user_data_dir=str(profile_dir))
    )
    try:
        await browser.start()
        logger.info("Session %s browser open for manual login", session_id)
        deadline = time.monotonic() + settings.session_open_timeout_s
        # Polls a DB flag so /sessions/{id}/close can end the job cross-process.
        while time.monotonic() < deadline:  # noqa: ASYNC110
            row = await db.arun(db.get_session, session_id)
            if row is None or row.close_requested:
                break
            await asyncio.sleep(1)
        else:
            logger.info(
                "Session %s browser closed after %ds timeout",
                session_id,
                settings.session_open_timeout_s,
            )
    finally:
        await db.arun(db.update_session, session_id, close_requested=False)
        await db.arun(db.unlock_session, session_id)
        try:
            await browser.kill()
        except Exception:
            logger.warning(
                "Session %s: browser cleanup failed", session_id, exc_info=True
            )
        logger.info("Session %s browser closed", session_id)


async def session_cleanup_job(ctx: dict) -> None:
    """Sweep expired sessions + orphaned/stale profile dirs."""
    profiles_root = settings.browser_profiles_dir
    session_ids = await db.arun(db.all_session_ids)
    stale_task_dirs = set(await db.arun(db.stale_task_profile_dirs))

    removed_dirs = 0
    cutoff = datetime.now(UTC) - timedelta(days=1)
    for d in profiles_root.iterdir() if profiles_root.exists() else []:
        if not d.is_dir():
            continue
        if d.name in session_ids:
            continue  # live session profile
        # Remove if terminal-task profile or an orphan dir older than a day.
        stale_task = d.name in stale_task_dirs
        orphan = (
            not stale_task
            and not await db.arun(db.task_exists, d.name)
            and datetime.fromtimestamp(d.stat().st_mtime, UTC) < cutoff
        )
        if stale_task or orphan:
            shutil.rmtree(d, ignore_errors=True)
            removed_dirs += 1

    expired_ids = await db.arun(db.delete_expired_sessions)
    for sid in expired_ids:
        shutil.rmtree(profiles_root / sid, ignore_errors=True)

    if expired_ids or removed_dirs:
        logger.info(
            "Session cleanup: %d expired sessions, %d profile dirs removed",
            len(expired_ids),
            removed_dirs,
        )


async def startup(ctx: dict) -> None:
    await db.arun(init_db)
    stale = await db.arun(db.fail_stale_tasks)
    logger.info(
        "Worker started, concurrency=%d, stale_tasks_failed=%d",
        settings.worker_concurrency,
        stale,
    )


class WorkerSettings:
    functions = [run_task_job, approval_response_job, human_resume_job]
    cron_jobs = [
        cron(
            session_cleanup_job,
            minute=set(range(0, 60, 15)),
            run_at_startup=True,
        )
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_concurrency
    job_timeout = settings.task_timeout_s + 60
    max_tries = 1


class SessionWorkerSettings:
    """Dedicated lane for headed-login browsers — never starves task jobs."""

    functions = [open_session_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.session_queue_name
    max_jobs = 1
    job_timeout = settings.session_open_timeout_s + 60
    max_tries = 1
