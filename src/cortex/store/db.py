import json
import logging
import uuid
from datetime import datetime

from sqlmodel import Field, Session, SQLModel, create_engine, select

from cortex.config import settings
from cortex.models import TaskRequest, TaskStatus, utcnow

logger = logging.getLogger("cortex.db")


class TaskRow(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    task: str
    start_url: str | None = None
    allowed_domains_json: str = "[]"
    session_id: str | None = None
    max_steps: int | None = None
    headless: bool | None = None
    idempotency_key: str | None = Field(default=None, index=True)
    status: str = TaskStatus.QUEUED
    result: str | None = None
    error: str | None = None
    steps_taken: int = 0
    cancel_requested: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


_engine = create_engine(settings.database_url, echo=False)


def init_db() -> None:
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.browser_profiles_dir.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(_engine)


def create_task(req: TaskRequest) -> tuple[TaskRow, bool]:
    """Insert a task row. Returns (row, created). Idempotent on idempotency_key."""
    with Session(_engine) as s:
        if req.idempotency_key:
            existing = s.exec(
                select(TaskRow).where(TaskRow.idempotency_key == req.idempotency_key)
            ).first()
            if existing:
                return existing, False
        row = TaskRow(
            task=req.task,
            start_url=req.start_url,
            allowed_domains_json=json.dumps(req.allowed_domains),
            session_id=req.session_id,
            max_steps=req.max_steps,
            headless=req.headless,
            idempotency_key=req.idempotency_key,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row, True


def get_task(task_id: str) -> TaskRow | None:
    with Session(_engine) as s:
        return s.get(TaskRow, task_id)


def list_tasks(limit: int = 50, offset: int = 0) -> list[TaskRow]:
    with Session(_engine) as s:
        return list(
            s.exec(
                select(TaskRow).order_by(TaskRow.created_at.desc()).offset(offset).limit(limit)  # type: ignore[attr-defined]
            ).all()
        )


def update_task(task_id: str, **fields) -> TaskRow | None:
    with Session(_engine) as s:
        row = s.get(TaskRow, task_id)
        if not row:
            return None
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = utcnow()
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def request_cancel(task_id: str) -> TaskRow | None:
    return update_task(task_id, cancel_requested=True)


def is_cancel_requested(task_id: str) -> bool:
    row = get_task(task_id)
    return bool(row and row.cancel_requested)
