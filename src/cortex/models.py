from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

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
    approval_actions: list[str] = Field(
        default_factory=list,
        description="browser-use action names requiring human approval before executing.",
    )
    session_id: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=500)
    headless: bool | None = None
    priority: Literal["low", "normal", "high"] = "normal"
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
    retry_count: int = 0
    priority: str = "normal"
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
    details: str | None = None
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


class ApprovalDecision(BaseModel):
    approve: bool


class ApiKeyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    daily_limit: int | None = Field(default=None, ge=1)


class ApiKeyCreated(BaseModel):
    id: str
    label: str
    key: str  # plaintext, returned exactly once


class ApiKeyInfo(BaseModel):
    id: str
    label: str
    prefix: str
    daily_limit: int | None = None
    requests_today: int = 0
    disabled: bool = False
    created_at: datetime
    last_used_at: datetime | None = None


class TaskEventResponse(BaseModel):
    id: str
    task_id: str
    kind: str
    n: int | None = None
    url: str | None = None
    actions: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    payload: dict | None = None
    created_at: datetime


class StatsResponse(BaseModel):
    tasks_total: int
    by_status: dict[str, int]
    success_rate: float | None = None
    avg_steps: float | None = None
    avg_duration_s: float | None = None
    tokens_in_total: int | None = None
    tokens_out_total: int | None = None
    cost_usd_total: float | None = None
    running_now: int = 0
    queue_depth: int | None = None
    session_queue_depth: int | None = None


class ErrorResponse(BaseModel):
    detail: str
