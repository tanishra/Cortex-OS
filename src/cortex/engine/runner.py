"""Engine: runs a browser-use Agent for one task row and records artifacts."""

import asyncio
import json
import logging
import time
from urllib.parse import urlparse

from browser_use import Agent, Browser, BrowserProfile, ChatOpenAI

from cortex.config import settings
from cortex.engine.checkpoint import resume_task_text
from cortex.engine.escalation import detect_human_wall
from cortex.engine.gates import make_action_gate, make_allowlist
from cortex.engine.limits import domain_wait, host_of
from cortex.engine.prompts import SAFETY_EXTENSION
from cortex.engine.retry import TransientTaskError, classify
from cortex.models import StepRecord, TaskStatus, utcnow
from cortex.notify import notify_human
from cortex.store import artifacts, db
from cortex.telemetry import tracer
from cortex.utils import spawn
from cortex.vault import credentials

logger = logging.getLogger("cortex.engine")

# Task_id -> {"agent": Agent, "state": dict} — in-process handles for
# pause/resume/stop and shared status cache (worker process only).
_RUNNING: dict[str, dict] = {}


def running_agent(task_id: str) -> Agent | None:
    entry = _RUNNING.get(task_id)
    return entry["agent"] if entry else None


def running_state(task_id: str) -> dict | None:
    """The task's mutable state cache — used by worker jobs to stay coherent."""
    entry = _RUNNING.get(task_id)
    return entry["state"] if entry else None


def _action_name(action) -> str:
    """Best-effort name of a single browser-use action."""
    try:
        dumped = action.model_dump(exclude_unset=True)
        return next(iter(dumped.keys()), "unknown")
    except Exception:
        return type(action).__name__


def _action_names(output) -> list[str]:
    """Extract action names from an AgentOutput's action list, defensively."""
    return [_action_name(a) for a in getattr(output, "action", []) or []]


def _host_matches(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def _detect_wall(task_id: str, browser_state, agent_output) -> str | None:
    """Serialize DOM + agent text and run the human-wall detector."""
    try:
        dom_text = browser_state.dom_state.llm_representation()
    except Exception:
        logger.debug("Task %s: DOM serialization failed", task_id, exc_info=True)
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
    return detect_human_wall(
        browser_state.url or "",
        browser_state.title or "",
        f"{dom_text}\n{agent_text}",
    )


async def run_task(task_id: str, redis=None) -> None:
    """Execute one queued task end-to-end. Updates DB status and writes artifacts."""
    try:
        await _run_task(task_id, redis=redis)
    except TransientTaskError:
        raise
    except Exception as exc:
        # Setup-phase crash (profile mkdir, browser/agent construction, DB
        # reads) — before the inner try exists. Classify + record so the
        # task never stays stuck 'queued'.
        logger.exception("Task %s crashed during setup", task_id)
        try:
            await db.arun(
                db.record_event,
                task_id,
                "error",
                payload_json=json.dumps({"error": type(exc).__name__}),
            )
        except Exception:
            pass
        if classify(exc) == "transient":
            raise TransientTaskError(f"{type(exc).__name__}: {exc}") from exc
        await db.arun(
            db.update_task,
            task_id,
            status=TaskStatus.FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )
        try:
            await db.arun(
                db.record_event,
                task_id,
                "status",
                payload_json=json.dumps({"to": "failed", "reason": "setup_crash"}),
            )
        except Exception:
            pass


async def _run_task(task_id: str, redis=None) -> None:
    row = await db.arun(db.get_task, task_id)
    if not row:
        logger.error("run_task called for unknown task %s", task_id)
        return
    if row.status == TaskStatus.CANCELLED:
        return

    async def emit(kind: str, **fields) -> None:
        """Telemetry write — must never break task execution."""
        try:
            await db.arun(db.record_event, task_id, kind, **fields)
        except Exception:
            logger.warning(
                "Task %s: failed to record %s event", task_id, kind, exc_info=True
            )

    # Per-domain start throttle — before session lock so we never sleep
    # while holding a profile.
    if redis is not None and settings.rate_limit_per_domain_s > 0:
        await domain_wait(
            redis, host_of(row.start_url), settings.rate_limit_per_domain_s
        )

    if row.session_id:
        session = await db.arun(db.get_session, row.session_id)
        if session and db.is_session_expired(session):
            await emit(
                "status",
                payload_json=json.dumps(
                    {"to": "failed", "reason": "session_expired"}
                ),
            )
            await db.arun(
                db.update_task,
                task_id,
                status=TaskStatus.FAILED,
                error="session_expired: session TTL elapsed",
            )
            return
        if not await db.arun(db.try_lock_session, row.session_id, task_id):
            await emit(
                "status",
                payload_json=json.dumps(
                    {"to": "failed", "reason": "session_in_use"}
                ),
            )
            await db.arun(
                db.update_task,
                task_id,
                status=TaskStatus.FAILED,
                error="session_in_use: browser profile is held by another task/session",
            )
            return

    resume = None
    if row.resume_from:
        try:
            resume = json.loads(row.resume_from)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Task %s: corrupt resume_from — starting fresh", task_id
            )
        else:
            if not isinstance(resume, dict):
                logger.warning(
                    "Task %s: corrupt resume_from — starting fresh", task_id
                )
                resume = None
    if resume or row.resume_from:
        await db.arun(db.update_task, task_id, resume_from=None)
    if resume:
        logger.info(
            "Task %s resuming from checkpoint: %s", task_id, resume.get("last_url")
        )

    task_text = row.task
    if resume:
        task_text = resume_task_text(row.task, resume)
    elif row.start_url:
        task_text = f"Start by navigating to {row.start_url}.\n\nTask: {row.task}"

    allowed_domains = json.loads(row.allowed_domains_json or "[]")
    approval_domains = json.loads(row.approval_domains_json or "[]")
    approval_actions = set(json.loads(row.approval_actions_json or "[]"))
    allowed_actions = set(json.loads(row.allowed_actions_json or "[]"))
    token_budget = row.max_tokens if row.max_tokens is not None else settings.task_max_tokens
    headless = row.headless if row.headless is not None else settings.browser_headless

    profile_dir = settings.browser_profiles_dir / (row.session_id or task_id)
    profile_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "domain_blocked": False,
        "current_url": row.start_url or "",
        "status": TaskStatus.QUEUED,
        "approval_pending": False,
        "last_step_ts": time.monotonic(),
        # Any fresh agent (resume OR retry attempt) counts steps from 1 —
        # offset keeps DB count + artifact filenames monotonic.
        "step_offset": row.steps_taken,
        "steps_done": row.steps_taken,
        "recent_goals": [],
        # Resumed from waiting_human → first wall re-detection pauses as
        # usual but skips re-notifying (same wall, already reported).
        "suppress_wall_notify": bool(
            resume and resume.get("prev_status") == "waiting_human"
        ),
        "cost_exceeded": False,
        "tool_loop": "",
        "recent_actions": [],
        "latency_exceeded": False,
        "start_ts": time.monotonic(),
    }
    agent_holder: dict = {}

    async def set_status(status: TaskStatus, **fields) -> None:
        await db.arun(db.update_task, task_id, status=status, **fields)
        state["status"] = status
        await emit("status", payload_json=json.dumps({"to": str(status)}))

    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        max_completion_tokens=settings.openai_max_completion_tokens,
    )

    browser = Browser(
        browser_profile=BrowserProfile(
            headless=headless,
            user_data_dir=str(profile_dir),
            chromium_sandbox=settings.browser_chromium_sandbox,
        )
    )

    sensitive_data = None
    if row.session_id:
        sensitive_data = await db.arun(credentials.sensitive_data_for, row.session_id)
        await db.arun(db.update_session, row.session_id, last_used_at=utcnow())

    async def on_step(browser_state, agent_output, step_n: int) -> None:
        url = browser_state.url or ""
        state["current_url"] = url
        n = step_n + state["step_offset"]
        state["steps_done"] = n
        if (
            settings.task_latency_budget_s > 0
            and not state["latency_exceeded"]
            and time.monotonic() - state["start_ts"] > settings.task_latency_budget_s
        ):
            state["latency_exceeded"] = True
            await emit(
                "latency_exceeded",
                n=n,
                payload_json=json.dumps(
                    {"budget_s": settings.task_latency_budget_s}
                ),
            )
            logger.warning("Task %s exceeded latency budget at step %d", task_id, n)
        goal = getattr(agent_output, "next_goal", None)
        if goal:
            state["recent_goals"] = (state["recent_goals"] + [f"step {n}: {goal}"])[-3:]
        with tracer().start_as_current_span(
            "task.step",
            attributes={
                "task.id": task_id,
                "step.n": n,
                "step.url": url,
                "step.actions": ",".join(_action_names(agent_output)),
            },
        ):
            await _on_step_inner(browser_state, agent_output, n, url)

    async def _on_step_inner(browser_state, agent_output, n: int, url: str) -> None:
        if allowed_domains and not _host_matches(url, allowed_domains):
            state["domain_blocked"] = True
            logger.warning("Task %s: domain blocked at %s", task_id, url)

        # Human escalation first: CAPTCHA/2FA wall wins over the approval
        # gate — even an approved action can't pass a human-only wall.
        wall = None
        if state["status"] != TaskStatus.WAITING_HUMAN:
            wall = _detect_wall(task_id, browser_state, agent_output)
            if wall:
                await set_status(TaskStatus.WAITING_HUMAN)
                agent_holder["agent"].pause()
                logger.warning(
                    "Task %s: human wall detected (%s) at %s", task_id, wall, url
                )
                if state["suppress_wall_notify"]:
                    state["suppress_wall_notify"] = False
                else:
                    spawn(notify_human(task_id, url, wall))

        # Human-in-the-loop gate: entering an approval domain pauses the
        # agent once and flips the task to waiting_approval until responded.
        if (
            not wall
            and state["status"] == TaskStatus.RUNNING
            and approval_domains
            and _host_matches(url, approval_domains)
            and not state["domain_blocked"]
            and not state["approval_pending"]
        ):
            existing = await db.arun(db.pending_approval_for_task, task_id)
            if existing is None:
                await db.arun(
                    db.create_approval, task_id, "agent entered gated domain", url
                )
                spawn(notify_human(task_id, url, "approval_domain"))
            state["approval_pending"] = True
            await set_status(TaskStatus.WAITING_APPROVAL)
            agent_holder["agent"].pause()
            logger.info("Task %s: approval requested for %s", task_id, url)

        actions = _action_names(agent_output)
        state["recent_actions"] = (state["recent_actions"] + actions)[-6:]
        now = time.monotonic()
        duration_ms = int((now - state["last_step_ts"]) * 1000)
        state["last_step_ts"] = now
        await emit(
            "step", n=n, url=url, actions_json=json.dumps(actions),
            duration_ms=duration_ms,
        )
        step = StepRecord(
            n=n,
            url=url,
            title=browser_state.title or "",
            actions=actions,
            evaluation=getattr(agent_output, "evaluation_previous_goal", None),
            memory=getattr(agent_output, "memory", None),
            next_goal=getattr(agent_output, "next_goal", None),
            errors=list(getattr(browser_state, "browser_errors", []) or []),
        )
        await artifacts.write_step(
            task_id,
            step,
            getattr(browser_state, "screenshot", None),
        )
        await db.arun(db.update_task, task_id, steps_taken=n)

    async def on_done(history) -> None:
        logger.info("Task %s done callback: %d steps", task_id, len(history.agent_steps()))

    async def should_stop() -> bool:
        if state["domain_blocked"] or await db.arun(db.is_cancel_requested, task_id):
            return True
        recent = state["recent_actions"][-5:]
        if len(recent) == 5 and len(set(recent)) == 1:
            state["tool_loop"] = recent[0]
            logger.warning(
                "Task %s: tool loop — '%s' repeated 5x, stopping", task_id, recent[0]
            )
            return True
        if token_budget > 0:
            try:
                usage = await agent.token_cost_service.get_usage_summary()
                if usage.total_tokens > token_budget:
                    state["cost_exceeded"] = True
                    logger.warning(
                        "Task %s token budget %d exceeded (%d used)",
                        task_id,
                        token_budget,
                        usage.total_tokens,
                    )
                    return True
            except Exception:
                logger.debug("Task %s: usage check failed", task_id, exc_info=True)
        return await db.arun(db.has_denied_approval, task_id)

    agent = Agent(
        task=task_text,
        llm=llm,
        browser=browser,
        fallback_llm=(
            ChatOpenAI(
                model=settings.openai_fallback_model,
                api_key=settings.openai_api_key,
                max_completion_tokens=settings.openai_max_completion_tokens,
            )
            if settings.openai_fallback_model
            else None
        ),
        sensitive_data=sensitive_data,
        use_vision="auto",
        max_failures=5,
        step_timeout=settings.step_timeout_s,
        extend_system_message=SAFETY_EXTENSION,
        register_new_step_callback=on_step,
        register_done_callback=on_done,
        register_should_stop_callback=should_stop,
        task_id=task_id,
        calculate_cost=True,
    )
    agent_holder["agent"] = agent
    _RUNNING[task_id] = {"agent": agent, "state": state}

    async def _watch_external():
        """Cross-process control: human-resume / approval / cancel signals are
        DB writes that any worker can make — this poll lets them reach the
        agent in whichever process owns it."""
        while True:
            await asyncio.sleep(1)
            try:
                row_now = await db.arun(db.get_task, task_id)
                if row_now is None:
                    continue
                if row_now.resume_requested:
                    await db.arun(
                        db.update_task, task_id, resume_requested=False
                    )
                    agent.resume()
                    logger.info("Task %s: resumed via resume_requested", task_id)
                if state["status"] == TaskStatus.WAITING_APPROVAL:
                    pending = await db.arun(db.pending_approval_for_task, task_id)
                    if pending is None:
                        if await db.arun(db.has_denied_approval, task_id):
                            agent.stop()
                        else:
                            state["approval_pending"] = False
                            state["status"] = TaskStatus.RUNNING
                            agent.resume()
                            logger.info(
                                "Task %s: domain approval resolved, resumed",
                                task_id,
                            )
                if row_now.cancel_requested:
                    agent.stop()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Task %s: watcher poll failed", task_id, exc_info=True)

    watcher = asyncio.create_task(_watch_external())

    # Tracing wrapper is always installed — near-zero cost with no-op tracer.
    original_act = agent.tools.act

    async def traced_act(*args, **kwargs):
        name = _action_name(args[0]) if args else "?"
        with tracer().start_as_current_span(
            "task.action",
            attributes={"task.id": task_id, "action.name": name},
        ):
            return await original_act(*args, **kwargs)

    agent.tools.act = traced_act

    if approval_actions:
        agent.tools.act = make_action_gate(
            task_id,
            approval_actions,
            agent.tools.act,
            lambda: state["current_url"],
            state=state,
        )
        logger.info("Task %s: gating actions %s", task_id, sorted(approval_actions))

    # Allowlist wraps outermost — disallowed actions never reach gate/browser.
    # "done" is control flow, not a page action — always permitted, else the
    # agent could never terminate.
    if allowed_actions:
        agent.tools.act = make_allowlist(allowed_actions | {"done"}, agent.tools.act)
        logger.info(
            "Task %s: action allowlist %s", task_id, sorted(allowed_actions)
        )

    await set_status(TaskStatus.RUNNING)

    try:
        budget = row.max_steps or settings.max_steps
        if resume:
            budget = max(1, budget - row.steps_taken)
        with tracer().start_as_current_span(
            "task.run",
            attributes={
                "task.id": task_id,
                "task.session_id": row.session_id or "",
                "task.resumed": bool(resume),
            },
        ):
            history = await agent.run(max_steps=budget)

        if state["domain_blocked"]:
            await set_status(
                TaskStatus.FAILED,
                error="domain_blocked: agent navigated outside allowed_domains",
            )
            return

        if await db.arun(db.is_cancel_requested, task_id):
            await set_status(TaskStatus.CANCELLED, error="cancelled by user")
            return

        if await db.arun(db.has_denied_approval, task_id):
            await set_status(TaskStatus.CANCELLED, error="approval denied")
            return

        if state["tool_loop"]:
            await set_status(
                TaskStatus.FAILED,
                error=f"tool_loop: action '{state['tool_loop']}' repeated 5 times",
            )
            return

        if state["cost_exceeded"]:
            await set_status(
                TaskStatus.FAILED,
                error=f"cost_exceeded: token budget {token_budget} exceeded",
            )
            return

        if state["status"] in (
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.WAITING_HUMAN,
        ):
            await set_status(TaskStatus.RUNNING)

        final = history.final_result()
        success = history.is_successful()
        usage = getattr(history, "usage", None)
        await emit(
            "finished",
            tokens_in=getattr(usage, "total_prompt_tokens", None),
            tokens_out=getattr(usage, "total_completion_tokens", None),
            cost_usd=(
                getattr(usage, "total_prompt_cost", 0.0)
                + getattr(usage, "total_completion_cost", 0.0)
            )
            if usage
            else None,
        )
        await set_status(
            TaskStatus.DONE if success else TaskStatus.FAILED,
            result=str(final) if final is not None else None,
            error=None if success else (str(history.errors() or "agent did not complete task")),
        )
        logger.info(
            "Task %s finished: success=%s steps=%d",
            task_id,
            success,
            len(history.agent_steps()),
        )

    except asyncio.CancelledError:
        # Job-level timeout (wait_for) — persist a checkpoint so the retry
        # resumes warm instead of starting cold. Re-raise for the worker.
        checkpoint = {
            "last_url": state["current_url"],
            "steps_taken": state["steps_done"],
            "summary": "\n".join(state["recent_goals"]),
            "prev_status": str(state["status"]),
        }
        try:
            await db.arun(
                db.update_task, task_id, resume_from=json.dumps(checkpoint)
            )
        except Exception:
            logger.warning(
                "Task %s: failed to persist checkpoint on cancel",
                task_id,
                exc_info=True,
            )
        raise
    except Exception as exc:
        logger.exception("Task %s crashed", task_id)
        await emit("error", payload_json=json.dumps({"error": type(exc).__name__}))
        if classify(exc) == "transient":
            # Persist a live checkpoint so the retry attempt resumes warm —
            # otherwise a crashed run restarts cold after one resume.
            checkpoint = {
                "last_url": state["current_url"],
                "steps_taken": state["steps_done"],
                "summary": "\n".join(state["recent_goals"]),
                "prev_status": str(state["status"]),
            }
            await db.arun(
                db.update_task, task_id, resume_from=json.dumps(checkpoint)
            )
            raise TransientTaskError(f"{type(exc).__name__}: {exc}") from exc
        await set_status(TaskStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
    finally:
        watcher.cancel()
        _RUNNING.pop(task_id, None)
        if row.session_id:
            await db.arun(db.unlock_session, row.session_id)
        try:
            await browser.kill()
        except Exception:
            logger.warning("Task %s: browser cleanup failed", task_id, exc_info=True)
