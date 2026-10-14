from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_HUMAN = "waiting_human"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRequest(BaseModel):
    task: str = Field(min_length=3, max_length=10_000)
    start_url: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    session_id: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=500)
    headless: bool | None = None
    idempotency_key: str | None = None


class StepRecord(BaseModel):
    n: int
    url: str
    title: str
    actions: list[str] = Field(default_factory=list)
    evaluation: str | None = None
    memory: str | None = None
    next_goal: str | None = None
    screenshot: str | None = None  # relative path inside task artifact dir
    errors: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utcnow)


class TaskResponse(BaseModel):
    id: str
    status: TaskStatus
    task: str
    result: str | None = None
    error: str | None = None
    steps_taken: int = 0
    created_at: datetime
    updated_at: datetime


class ErrorResponse(BaseModel):
    detail: str
