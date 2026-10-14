import pytest
from pydantic import ValidationError

from cortex.models import StepRecord, TaskRequest, TaskStatus


def test_task_request_minimal():
    req = TaskRequest(task="open example.com")
    assert req.task == "open example.com"
    assert req.allowed_domains == []


def test_task_request_rejects_too_short():
    with pytest.raises(ValidationError):
        TaskRequest(task="hi")


def test_task_status_values():
    assert TaskStatus.QUEUED == "queued"
    assert TaskStatus.DONE == "done"


def test_step_record_defaults():
    step = StepRecord(n=1, url="https://example.com", title="Example")
    assert step.actions == []
    assert step.screenshot is None
