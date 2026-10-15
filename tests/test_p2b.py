import asyncio
import json
from unittest.mock import AsyncMock

from cortex.engine.gates import make_action_gate
from cortex.models import TaskRequest, TaskStatus
from cortex.store import db


class FakeAction:
    """Mimics ActionModel.model_dump(exclude_unset=True)."""

    def __init__(self, name: str, params: dict):
        self._name = name
        self._params = params

    def model_dump(self, exclude_unset=True):
        return {self._name: self._params}


def _make_task(task="gate me", actions=None):
    db.init_db()
    row, _ = db.create_task(TaskRequest(task=task, approval_actions=actions or []))
    db.update_task(row.id, status=TaskStatus.RUNNING)
    return row


def test_ungated_action_passes_through():
    row = _make_task(actions=["click_element_by_index"])
    original = AsyncMock(return_value="ok")
    gate = make_action_gate(row.id, {"click_element_by_index"}, original, lambda: "")

    out = asyncio.run(
        gate(action=FakeAction("scroll_down", {"amount": 300}))
    )
    assert out == "ok"
    assert db.list_approvals(task_id=row.id) == []


def test_gated_action_creates_approval_and_runs_on_approve():
    row = _make_task(actions=["click_element_by_index"])
    original = AsyncMock(return_value="executed")
    gate = make_action_gate(
        row.id, {"click_element_by_index"}, original, lambda: "https://shop.com"
    )

    async def approve_soon():
        await asyncio.sleep(0.2)
        a = db.pending_approval_for_task(row.id)
        db.resolve_approval(a.id, "approved")

    async def run():
        task = asyncio.create_task(
            gate(action=FakeAction("click_element_by_index", {"index": 7}))
        )
        await approve_soon()
        return await task

    assert asyncio.run(run()) == "executed"
    original.assert_awaited_once()
    approval = db.list_approvals(task_id=row.id, status=None)[0]
    assert approval.reason == "gated action: click_element_by_index"
    assert json.loads(approval.details)["params"]["index"] == 7
    assert db.get_task(row.id).status == TaskStatus.RUNNING


def test_gated_action_denied_returns_error_result():
    row = _make_task(actions=["input_text"])
    original = AsyncMock()
    gate = make_action_gate(row.id, {"input_text"}, original, lambda: "")

    async def deny_soon():
        await asyncio.sleep(0.2)
        a = db.pending_approval_for_task(row.id)
        db.resolve_approval(a.id, "denied")

    async def run():
        task = asyncio.create_task(
            gate(action=FakeAction("input_text", {"index": 1, "text": "x"}))
        )
        await deny_soon()
        return await task

    result = asyncio.run(run())
    assert result.error == "action 'input_text' denied by human"
    original.assert_not_awaited()


def test_pending_approval_reused_on_retry():
    row = _make_task(actions=["done"])
    original = AsyncMock()
    gate = make_action_gate(row.id, {"done"}, original, lambda: "")

    db.create_approval(row.id, "gated action: done", "", '{"action": "done"}')
    db.update_task(row.id, status=TaskStatus.WAITING_APPROVAL)

    async def deny_soon():
        await asyncio.sleep(0.2)
        a = db.pending_approval_for_task(row.id)
        db.resolve_approval(a.id, "denied")

    async def run():
        task = asyncio.create_task(gate(action=FakeAction("done", {"text": "fin"})))
        await deny_soon()
        return await task

    asyncio.run(run())
    assert len(db.list_approvals(task_id=row.id, status=None)) == 1


def test_approval_actions_roundtrip():
    row = _make_task(actions=["click_element_by_index", "send_keys"])
    fetched = db.get_task(row.id)
    assert json.loads(fetched.approval_actions_json) == [
        "click_element_by_index",
        "send_keys",
    ]
