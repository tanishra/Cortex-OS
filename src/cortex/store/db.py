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
    approval_domains_json: str = "[]"
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


class SessionRow(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    name: str = Field(index=True)
    close_requested: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None


class CredentialRow(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    session_id: str = Field(index=True)
    domain: str
    data_encrypted: bytes
    created_at: datetime = Field(default_factory=utcnow)


class ApprovalRow(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    task_id: str = Field(index=True)
    reason: str
    url: str | None = None
    status: str = "pending"  # pending | approved | denied
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


_engine = create_engine(settings.database_url, echo=False)


def init_db() -> None:
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.browser_profiles_dir.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(_engine)


# --- tasks ---


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
            approval_domains_json=json.dumps(req.approval_domains),
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
                select(TaskRow)
                .order_by(TaskRow.created_at.desc())  # type: ignore[attr-defined]
                .offset(offset)
                .limit(limit)
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


# --- sessions ---


def create_session(name: str) -> SessionRow:
    with Session(_engine) as s:
        row = SessionRow(name=name)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def get_session(session_id: str) -> SessionRow | None:
    with Session(_engine) as s:
        return s.get(SessionRow, session_id)


def get_session_by_name(name: str) -> SessionRow | None:
    with Session(_engine) as s:
        return s.exec(select(SessionRow).where(SessionRow.name == name)).first()


def list_sessions() -> list[SessionRow]:
    with Session(_engine) as s:
        return list(s.exec(select(SessionRow)).all())


def update_session(session_id: str, **fields) -> SessionRow | None:
    with Session(_engine) as s:
        row = s.get(SessionRow, session_id)
        if not row:
            return None
        for k, v in fields.items():
            setattr(row, k, v)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def delete_session(session_id: str) -> bool:
    with Session(_engine) as s:
        row = s.get(SessionRow, session_id)
        if not row:
            return False
        s.delete(row)
        s.commit()
        return True


# --- credentials ---


def upsert_credential(session_id: str, domain: str, data_encrypted: bytes) -> CredentialRow:
    with Session(_engine) as s:
        row = s.exec(
            select(CredentialRow).where(
                CredentialRow.session_id == session_id, CredentialRow.domain == domain
            )
        ).first()
        if row:
            row.data_encrypted = data_encrypted
        else:
            row = CredentialRow(
                session_id=session_id, domain=domain, data_encrypted=data_encrypted
            )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def get_credentials_for_session(session_id: str) -> list[CredentialRow]:
    with Session(_engine) as s:
        return list(
            s.exec(select(CredentialRow).where(CredentialRow.session_id == session_id)).all()
        )


def delete_credential(session_id: str, domain: str) -> bool:
    with Session(_engine) as s:
        row = s.exec(
            select(CredentialRow).where(
                CredentialRow.session_id == session_id, CredentialRow.domain == domain
            )
        ).first()
        if not row:
            return False
        s.delete(row)
        s.commit()
        return True


# --- approvals ---


def create_approval(task_id: str, reason: str, url: str | None = None) -> ApprovalRow:
    with Session(_engine) as s:
        row = ApprovalRow(task_id=task_id, reason=reason, url=url)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def get_approval(approval_id: str) -> ApprovalRow | None:
    with Session(_engine) as s:
        return s.get(ApprovalRow, approval_id)


def list_approvals(status: str | None = "pending") -> list[ApprovalRow]:
    with Session(_engine) as s:
        q = select(ApprovalRow)
        if status:
            q = q.where(ApprovalRow.status == status)
        return list(s.exec(q.order_by(ApprovalRow.created_at.desc())).all())  # type: ignore[attr-defined]


def resolve_approval(approval_id: str, status: str) -> ApprovalRow | None:
    with Session(_engine) as s:
        row = s.get(ApprovalRow, approval_id)
        if not row or row.status != "pending":
            return None
        row.status = status
        row.resolved_at = utcnow()
        s.add(row)
        s.commit()
        s.refresh(row)
        return row
