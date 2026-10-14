"""Engine: runs a browser-use Agent for one task row and records artifacts."""

import json
import logging
from urllib.parse import urlparse

from browser_use import Agent, Browser, BrowserProfile, ChatOpenAI

from cortex.config import settings
from cortex.engine.prompts import SAFETY_EXTENSION
from cortex.models import StepRecord, TaskStatus
from cortex.store import artifacts, db
from cortex.vault import credentials

logger = logging.getLogger("cortex.engine")

# Task_id -> Agent for in-process pause/resume/stop (worker process only).
_RUNNING: dict[str, Agent] = {}


def running_agent(task_id: str) -> Agent | None:
    return _RUNNING.get(task_id)


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


def _host_matches(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


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
    approval_domains = json.loads(row.approval_domains_json or "[]")
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

    sensitive_data = None
    if row.session_id:
        sensitive_data = credentials.sensitive_data_for(row.session_id)
        db.update_session(row.session_id, last_used_at=db.utcnow())

    async def on_step(browser_state, agent_output, step_n: int) -> None:
        url = browser_state.url or ""
        if allowed_domains and not _host_matches(url, allowed_domains):
            state["domain_blocked"] = True
            logger.warning("Task %s: domain blocked at %s", task_id, url)

        # Human-in-the-loop gate: entering an approval domain pauses the
        # agent and flips the task to waiting_approval until responded.
        if (
            approval_domains
            and _host_matches(url, approval_domains)
            and not state["domain_blocked"]
        ):
            pending = [
                a
                for a in db.list_approvals("pending")
                if a.task_id == task_id and a.url == url
            ]
            if not pending:
                db.create_approval(task_id, "agent entered gated domain", url)
                db.update_task(task_id, status=TaskStatus.WAITING_APPROVAL)
                agent_holder["agent"].pause()
                logger.info("Task %s: approval requested for %s", task_id, url)

        step = StepRecord(
            n=step_n,
            url=url,
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
        if state["domain_blocked"] or db.is_cancel_requested(task_id):
            return True
        approval = next(
            (
                a
                for a in db.list_approvals("denied")
                if a.task_id == task_id
            ),
            None,
        )
        return approval is not None

    agent = Agent(
        task=task_text,
        llm=llm,
        browser=browser,
        sensitive_data=sensitive_data,
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
    _RUNNING[task_id] = agent

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

        if get_task_status(task_id) == TaskStatus.WAITING_APPROVAL:
            denied = any(
                a.status == "denied"
                for a in db.list_approvals(status=None)
                if a.task_id == task_id
            )
            if denied:
                db.update_task(task_id, status=TaskStatus.CANCELLED, error="approval denied")
                return
            db.update_task(task_id, status=TaskStatus.RUNNING)

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
        _RUNNING.pop(task_id, None)
        try:
            await browser.kill()
        except Exception:
            pass


def get_task_status(task_id: str) -> TaskStatus | None:
    row = db.get_task(task_id)
    return TaskStatus(row.status) if row else None
