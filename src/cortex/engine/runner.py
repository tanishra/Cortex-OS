"""Engine: runs a browser-use Agent for one task row and records artifacts."""

import json
import logging
from urllib.parse import urlparse

from browser_use import Agent, Browser, BrowserProfile, ChatOpenAI

from cortex.config import settings
from cortex.engine.prompts import SAFETY_EXTENSION
from cortex.models import StepRecord, TaskStatus
from cortex.store import artifacts, db

logger = logging.getLogger("cortex.engine")


def _action_names(output) -> list[str]:
    """Extract action names from an AgentOutput's action list, defensively."""
    names = []
    for action in getattr(output, "action", []) or []:
        try:
            dumped = action.model_dump(exclude_unset=True)
            names.append(next(iter(dumped.keys()), "unknown"))
        except Exception:
            names.append(type(action).__name__)
    return names


def _host_allowed(url: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


async def run_task(task_id: str) -> None:
    """Execute one queued task end-to-end. Updates DB status and writes artifacts."""
    row = db.get_task(task_id)
    if not row:
        logger.error("run_task called for unknown task %s", task_id)
        return

    task_text = row.task
    if row.start_url:
        task_text = f"Start by navigating to {row.start_url}.\n\nTask: {row.task}"

    allowed_domains = json.loads(row.allowed_domains_json or "[]")
    headless = row.headless if row.headless is not None else settings.browser_headless

    profile_dir = settings.browser_profiles_dir / (row.session_id or task_id)
    profile_dir.mkdir(parents=True, exist_ok=True)

    state = {"domain_blocked": False}
    agent_holder: dict = {}

    llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key)

    browser = Browser(
        browser_profile=BrowserProfile(
            headless=headless,
            user_data_dir=str(profile_dir),
        )
    )

    async def on_step(browser_state, agent_output, step_n: int) -> None:
        host_ok = _host_allowed(browser_state.url or "", allowed_domains)
        if not host_ok:
            state["domain_blocked"] = True
            logger.warning("Task %s: domain blocked at %s", task_id, browser_state.url)

        step = StepRecord(
            n=step_n,
            url=browser_state.url or "",
            title=browser_state.title or "",
            actions=_action_names(agent_output),
            evaluation=getattr(agent_output, "evaluation_previous_goal", None),
            memory=getattr(agent_output, "memory", None),
            next_goal=getattr(agent_output, "next_goal", None),
            errors=list(getattr(browser_state, "browser_errors", []) or []),
        )
        artifacts.write_step(task_id, step, getattr(browser_state, "screenshot", None))
        db.update_task(task_id, steps_taken=step_n)

    async def on_done(history) -> None:
        logger.info("Task %s done callback: %d steps", task_id, len(history.agent_steps()))

    async def should_stop() -> bool:
        return state["domain_blocked"] or db.is_cancel_requested(task_id)

    agent = Agent(
        task=task_text,
        llm=llm,
        browser=browser,
        use_vision="auto",
        max_failures=5,
        step_timeout=settings.step_timeout_s,
        extend_system_message=SAFETY_EXTENSION,
        register_new_step_callback=on_step,
        register_done_callback=on_done,
        register_should_stop_callback=should_stop,
        task_id=task_id,
    )
    agent_holder["agent"] = agent

    db.update_task(task_id, status=TaskStatus.RUNNING)

    try:
        history = await agent.run(max_steps=row.max_steps or settings.max_steps)

        if state["domain_blocked"]:
            db.update_task(
                task_id,
                status=TaskStatus.FAILED,
                error="domain_blocked: agent navigated outside allowed_domains",
            )
            return

        if db.is_cancel_requested(task_id):
            db.update_task(task_id, status=TaskStatus.CANCELLED, error="cancelled by user")
            return

        final = history.final_result()
        success = history.is_successful()
        db.update_task(
            task_id,
            status=TaskStatus.DONE if success else TaskStatus.FAILED,
            result=str(final) if final is not None else None,
            error=None if success else (str(history.errors() or "agent did not complete task")),
        )
        logger.info(
            "Task %s finished: success=%s steps=%d",
            task_id,
            success,
            len(history.agent_steps()),
        )

    except Exception as exc:
        logger.exception("Task %s crashed", task_id)
        db.update_task(task_id, status=TaskStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            await browser.kill()
        except Exception:
            pass
