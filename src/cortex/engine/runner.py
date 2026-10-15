"""Engine: runs a browser-use Agent for one task row and records artifacts."""

import json
import logging
from urllib.parse import urlparse

from browser_use import Agent, Browser, BrowserProfile, ChatOpenAI

from cortex.config import settings
from cortex.engine.escalation import detect_human_wall
from cortex.engine.gates import make_action_gate
from cortex.engine.prompts import SAFETY_EXTENSION
from cortex.models import StepRecord, TaskStatus, utcnow
from cortex.notify import notify_human
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
    row = await db.arun(db.get_task, task_id)
    if not row:
        logger.error("run_task called for unknown task %s", task_id)
        return

    if row.session_id and not await db.arun(
        db.try_lock_session, row.session_id, task_id
    ):
        await db.arun(
            db.update_task,
            task_id,
            status=TaskStatus.FAILED,
            error="session_in_use: browser profile is held by another task/session",
        )
        return

    task_text = row.task
    if row.start_url:
        task_text = f"Start by navigating to {row.start_url}.\n\nTask: {row.task}"

    allowed_domains = json.loads(row.allowed_domains_json or "[]")
    approval_domains = json.loads(row.approval_domains_json or "[]")
    approval_actions = set(json.loads(row.approval_actions_json or "[]"))
    headless = row.headless if row.headless is not None else settings.browser_headless

    profile_dir = settings.browser_profiles_dir / (row.session_id or task_id)
    profile_dir.mkdir(parents=True, exist_ok=True)

    state = {"domain_blocked": False, "current_url": row.start_url or ""}
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
        sensitive_data = await db.arun(credentials.sensitive_data_for, row.session_id)
        await db.arun(db.update_session, row.session_id, last_used_at=utcnow())

    async def on_step(browser_state, agent_output, step_n: int) -> None:
        url = browser_state.url or ""
        state["current_url"] = url
        if allowed_domains and not _host_matches(url, allowed_domains):
            state["domain_blocked"] = True
            logger.warning("Task %s: domain blocked at %s", task_id, url)

        # Human-in-the-loop gate: entering an approval domain pauses the
        # agent once and flips the task to waiting_approval until responded.
        if (
            approval_domains
            and _host_matches(url, approval_domains)
            and not state["domain_blocked"]
            and await db.arun(db.pending_approval_for_task, task_id) is None
        ):
            await db.arun(db.create_approval, task_id, "agent entered gated domain", url)
            await db.arun(db.update_task, task_id, status=TaskStatus.WAITING_APPROVAL)
            agent_holder["agent"].pause()
            logger.info("Task %s: approval requested for %s", task_id, url)

        # Human escalation: CAPTCHA/2FA wall → pause + waiting_human + webhook.
        current = await db.arun(db.get_task, task_id)
        if current and current.status != TaskStatus.WAITING_HUMAN:
            try:
                dom_text = browser_state.dom_state.llm_representation()
            except Exception:
                dom_text = ""
            agent_text = " ".join(
                filter(
                    None,
                    [
                        getattr(agent_output, "evaluation_previous_goal", None),
                        getattr(agent_output, "next_goal", None),
                    ],
                )
            )
            wall = detect_human_wall(
                url, browser_state.title or "", f"{dom_text}\n{agent_text}"
            )
            if wall:
                await db.arun(db.update_task, task_id, status=TaskStatus.WAITING_HUMAN)
                agent_holder["agent"].pause()
                logger.warning(
                    "Task %s: human wall detected (%s) at %s", task_id, wall, url
                )
                await notify_human(task_id, url, wall)

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
        await db.arun(
            artifacts.write_step,
            task_id,
            step,
            getattr(browser_state, "screenshot", None),
        )
        await db.arun(db.update_task, task_id, steps_taken=step_n)

    async def on_done(history) -> None:
        logger.info("Task %s done callback: %d steps", task_id, len(history.agent_steps()))

    async def should_stop() -> bool:
        if state["domain_blocked"] or await db.arun(db.is_cancel_requested, task_id):
            return True
        return await db.arun(db.has_denied_approval, task_id)

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

    if approval_actions:
        agent.tools.act = make_action_gate(
            task_id,
            approval_actions,
            agent.tools.act,
            lambda: state["current_url"],
        )
        logger.info("Task %s: gating actions %s", task_id, sorted(approval_actions))

    await db.arun(db.update_task, task_id, status=TaskStatus.RUNNING)

    try:
        history = await agent.run(max_steps=row.max_steps or settings.max_steps)

        if state["domain_blocked"]:
            await db.arun(
                db.update_task,
                task_id,
                status=TaskStatus.FAILED,
                error="domain_blocked: agent navigated outside allowed_domains",
            )
            return

        if await db.arun(db.is_cancel_requested, task_id):
            await db.arun(
                db.update_task,
                task_id,
                status=TaskStatus.CANCELLED,
                error="cancelled by user",
            )
            return

        if await db.arun(db.has_denied_approval, task_id):
            await db.arun(
                db.update_task,
                task_id,
                status=TaskStatus.CANCELLED,
                error="approval denied",
            )
            return

        current = await db.arun(db.get_task, task_id)
        if current and current.status in (
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.WAITING_HUMAN,
        ):
            await db.arun(db.update_task, task_id, status=TaskStatus.RUNNING)

        final = history.final_result()
        success = history.is_successful()
        await db.arun(
            db.update_task,
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
        await db.arun(
            db.update_task,
            task_id,
            status=TaskStatus.FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        _RUNNING.pop(task_id, None)
        if row.session_id:
            await db.arun(db.unlock_session, row.session_id)
        try:
            await browser.kill()
        except Exception:
            logger.warning("Task %s: browser cleanup failed", task_id, exc_info=True)
