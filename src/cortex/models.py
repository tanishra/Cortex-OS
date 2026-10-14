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
    approval_domains: list[str] = Field(
        default_factory=list,
        description="Pause for human approval whenever the agent is on one of these domains.",
    )
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


class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class SessionResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None = None


class CredentialRequest(BaseModel):
    domain: str = Field(min_length=1)
    fields: dict[str, str] = Field(
        min_length=1,
        description="Placeholder name -> secret value, e.g. {'x_username': 'me'}",
    )


class CredentialResponse(BaseModel):
    id: str
    session_id: str
    domain: str
    created_at: datetime


class ApprovalResponse(BaseModel):
    id: str
    task_id: str
    reason: str
    url: str | None = None
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


class ApprovalDecision(BaseModel):
    approve: bool


class ErrorResponse(BaseModel):
    detail: str
