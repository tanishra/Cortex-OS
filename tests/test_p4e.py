"""P4e — OpenTelemetry tracing."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from cortex import telemetry
from cortex.engine import runner
from cortex.models import TaskRequest, TaskStatus
from cortex.store import db


def _fake_ok(monkeypatch):
    history = SimpleNamespace(
        usage=None,
        agent_steps=lambda: [],
        final_result=lambda: "ok",
        is_successful=lambda: True,
        errors=lambda: [],
    )
    step_state = SimpleNamespace(
        url="https://a.com", title="A", dom_state=None, browser_errors=[]
    )
    out = SimpleNamespace(
        action=[], evaluation_previous_goal=None, memory=None, next_goal=None
    )

    class _A:
        def __init__(self, **kwargs):
            self._cb = kwargs["register_new_step_callback"]
            self.tools = SimpleNamespace(act=lambda *a, **k: None)

        async def run(self, max_steps=None):
            await self._cb(step_state, out, 1)
            return history

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )


def _use_provider(monkeypatch, provider):
    """OTel's global provider is set-once; swap internals for the test."""
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)


def test_init_tracing_disabled_noop(monkeypatch):
    monkeypatch.setattr(telemetry, "_provider", None)
    telemetry.init_tracing("svc", "")
    assert telemetry._provider is None


def test_init_tracing_enabled(monkeypatch):
    monkeypatch.setattr(telemetry, "_provider", None)
    # Global provider is set-once; the register call isn't the assertion point.
    monkeypatch.setattr(trace, "set_tracer_provider", lambda p: None)
    telemetry.init_tracing("svc", "http://localhost:4318")
    assert telemetry._provider is not None


def test_run_emits_spans(monkeypatch):
    db.init_db()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _use_provider(monkeypatch, provider)
    row, _ = db.create_task(TaskRequest(task="trace me"))
    _fake_ok(monkeypatch)
    asyncio.run(runner.run_task(row.id))

    names = {s.name for s in exporter.get_finished_spans()}
    assert "task.run" in names
    assert "task.step" in names
    run_span = next(s for s in exporter.get_finished_spans() if s.name == "task.run")
    assert run_span.attributes["task.id"] == row.id
    assert db.get_task(row.id).status == TaskStatus.DONE


def test_action_span(monkeypatch):
    db.init_db()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _use_provider(monkeypatch, provider)
    row, _ = db.create_task(TaskRequest(task="trace action"))
    act_called = []

    history = SimpleNamespace(
        usage=None,
        agent_steps=lambda: [],
        final_result=lambda: "ok",
        is_successful=lambda: True,
        errors=lambda: [],
    )

    async def real_act(*a, **k):
        act_called.append(True)
        return "done"

    class _Action:
        def model_dump(self, exclude_unset=True):
            return {"click_element_by_index": {"index": 3}}

    class _A:
        def __init__(self, **kwargs):
            self.tools = SimpleNamespace(act=real_act)

        async def run(self, max_steps=None):
            await self.tools.act(_Action())
            return history

    monkeypatch.setattr(runner, "Agent", _A)
    monkeypatch.setattr(runner, "ChatOpenAI", lambda **k: object())
    monkeypatch.setattr(
        runner, "Browser", lambda **k: SimpleNamespace(kill=AsyncMock())
    )
    asyncio.run(runner.run_task(row.id))
    names = {s.name for s in exporter.get_finished_spans()}
    assert "task.action" in names
    span = next(
        s for s in exporter.get_finished_spans() if s.name == "task.action"
    )
    assert span.attributes["action.name"] == "click_element_by_index"
    assert act_called
