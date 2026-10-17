import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel, create_engine, select, update

from cortex.config import settings
from cortex.models import TaskRequest, TaskStatus, utcnow

logger = logging.getLogger("cortex.db")

TERMINAL_STATUSES = (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED)
ACTIVE_STATUSES = (
    TaskStatus.RUNNING,
    TaskStatus.WAITING_APPROVAL,
    TaskStatus.WAITING_HUMAN,
)


class TaskRow(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    task: str
    start_url: str | None = None
    allowed_domains_json: str = "[]"
    approval_domains_json: str = "[]"
    approval_actions_json: str = "[]"
    session_id: str | None = None
    max_steps: int | None = None
    headless: bool | None = None
    priority: str = "normal"
    idempotency_key: str | None = Field(default=None, index=True, unique=True)
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
    locked_by: str | None = None  # owner holding the browser profile
    expires_at: datetime | None = None  # NULL = never expires (legacy rows)
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None


class CredentialRow(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    session_id: str = Field(index=True)
    domain: str
    data_encrypted: bytes
    created_at: datetime = Field(default_factory=utcnow)


class ApiKeyRow(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    label: str
    key_hash: str = Field(index=True, unique=True)
    prefix: str  # first chars of the key, for display only
    daily_limit: int | None = None  # NULL = unlimited
    requests_today: int = 0
    counter_day: str = ""  # YYYY-MM-DD the counter belongs to
    disabled: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None


class ApprovalRow(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    task_id: str = Field(index=True)
    reason: str
    url: str | None = None
    details: str | None = None  # JSON: gated action name + params
    status: str = "pending"  # pending | approved | denied
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


_ENGINE = create_engine(settings.database_url, echo=False)

_MUTABLE_TASK_FIELDS = {
    "status",
    "result",
    "error",
    "steps_taken",
    "cancel_requested",
}
_MUTABLE_SESSION_FIELDS = {
    "name",
    "close_requested",
    "locked_by",
    "last_used_at",
    "expires_at",
}


# Columns added after the initial schema — SQLite lacks CREATE IF NOT EXISTS
# for columns, so these are applied idempotently via PRAGMA checks.
_COLUMN_MIGRATIONS: dict[str, dict[str, str]] = {
    "taskrow": {
        "approval_actions_json": "VARCHAR DEFAULT '[]' NOT NULL",
        "priority": "VARCHAR DEFAULT 'normal' NOT NULL",
    },
    "sessionrow": {"locked_by": "VARCHAR", "expires_at": "DATETIME"},
    "approvalrow": {"details": "VARCHAR"},
}


def _migrate_columns() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(_ENGINE)
    with _ENGINE.begin() as conn:
        for table, columns in _COLUMN_MIGRATIONS.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col, ddl in columns.items():
                if col not in existing:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                    )
                    logger.info("Migrated %s.%s", table, col)


def init_db() -> None:
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.browser_profiles_dir.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(_ENGINE)
    _migrate_columns()


async def arun(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking DB call off the event loop (worker/engine hot paths)."""
    return await asyncio.to_thread(fn, *args, **kwargs)


# --- tasks ---


def create_task(req: TaskRequest) -> tuple[TaskRow, bool]:
    """Insert a task row. Returns (row, created). Idempotent on idempotency_key."""
    if req.idempotency_key:
        with Session(_ENGINE) as s:
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
        approval_actions_json=json.dumps(req.approval_actions),
        session_id=req.session_id,
        max_steps=req.max_steps,
        headless=req.headless,
        priority=req.priority,
        idempotency_key=req.idempotency_key,
    )
    with Session(_ENGINE) as s:
        s.add(row)
        try:
            s.commit()
        except IntegrityError:
            # Concurrent insert with same idempotency_key won the race.
            s.rollback()
            existing = s.exec(
                select(TaskRow).where(TaskRow.idempotency_key == req.idempotency_key)
            ).first()
            if existing:
                return existing, False
            raise
        s.refresh(row)
        return row, True


def get_task(task_id: str) -> TaskRow | None:
    with Session(_ENGINE) as s:
        return s.get(TaskRow, task_id)


def list_tasks(limit: int = 50, offset: int = 0) -> list[TaskRow]:
    with Session(_ENGINE) as s:
        return list(
            s.exec(
                select(TaskRow)
                .order_by(TaskRow.created_at.desc())  # type: ignore[attr-defined]
                .offset(offset)
                .limit(limit)
            ).all()
        )


def update_task(task_id: str, **fields) -> TaskRow | None:
    unknown = set(fields) - _MUTABLE_TASK_FIELDS
    if unknown:
        raise ValueError(f"update_task: unknown fields {sorted(unknown)}")
    with Session(_ENGINE) as s:
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


def fail_stale_tasks() -> int:
    """Mark active tasks as failed — called on worker startup after a restart."""
    with Session(_ENGINE) as s:
        result = s.exec(
            update(TaskRow)
            .where(TaskRow.status.in_(ACTIVE_STATUSES))  # type: ignore[attr-defined]
            .values(
                status=TaskStatus.FAILED,
                error="worker_restarted: task interrupted by worker restart",
                updated_at=utcnow(),
            )
        )
        s.commit()
        count = result.rowcount or 0
        if count:
            logger.warning("Marked %d stale task(s) failed on worker startup", count)
        return count


# --- sessions ---


def create_session(name: str) -> SessionRow:
    from datetime import timedelta

    with Session(_ENGINE) as s:
        row = SessionRow(
            name=name, expires_at=utcnow() + timedelta(seconds=settings.session_ttl_s)
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def get_session(session_id: str) -> SessionRow | None:
    with Session(_ENGINE) as s:
        return s.get(SessionRow, session_id)


def get_session_by_name(name: str) -> SessionRow | None:
    with Session(_ENGINE) as s:
        return s.exec(select(SessionRow).where(SessionRow.name == name)).first()


def list_sessions() -> list[SessionRow]:
    with Session(_ENGINE) as s:
        return list(s.exec(select(SessionRow)).all())


def update_session(session_id: str, **fields) -> SessionRow | None:
    unknown = set(fields) - _MUTABLE_SESSION_FIELDS
    if unknown:
        raise ValueError(f"update_session: unknown fields {sorted(unknown)}")
    with Session(_ENGINE) as s:
        row = s.get(SessionRow, session_id)
        if not row:
            return None
        for k, v in fields.items():
            setattr(row, k, v)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def try_lock_session(session_id: str, owner: str) -> bool:
    """Atomically claim a session's browser profile. False if already held."""
    with Session(_ENGINE) as s:
        result = s.exec(
            update(SessionRow)
            .where(SessionRow.id == session_id, SessionRow.locked_by.is_(None))  # type: ignore[attr-defined]
            .values(locked_by=owner)
        )
        s.commit()
        return (result.rowcount or 0) > 0


def unlock_session(session_id: str) -> None:
    with Session(_ENGINE) as s:
        s.exec(
            update(SessionRow)
            .where(SessionRow.id == session_id)
            .values(locked_by=None)
        )
        s.commit()


def delete_session(session_id: str) -> bool:
    with Session(_ENGINE) as s:
        row = s.get(SessionRow, session_id)
        if not row:
            return False
        s.delete(row)
        s.commit()
        return True


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def is_session_expired(row: SessionRow) -> bool:
    expires = _as_aware(row.expires_at)
    return expires is not None and expires < utcnow()


def delete_expired_sessions() -> list[str]:
    """Delete expired session rows; returns their ids (for profile cleanup)."""
    with Session(_ENGINE) as s:
        expired = [
            r
            for r in s.exec(select(SessionRow)).all()
            if is_session_expired(r) and r.locked_by is None
        ]
        ids = [r.id for r in expired]
        for r in expired:
            s.delete(r)
        s.commit()
        return ids


def stale_task_profile_dirs() -> list[str]:
    """Profile dir names belonging to terminal tasks older than 1 day."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=1)
    with Session(_ENGINE) as s:
        rows = s.exec(
            select(TaskRow.id).where(
                TaskRow.session_id.is_(None),  # type: ignore[attr-defined]
                TaskRow.status.in_(TERMINAL_STATUSES),  # type: ignore[attr-defined]
                TaskRow.updated_at < cutoff,
            )
        ).all()
        return list(rows)


def all_session_ids() -> set[str]:
    with Session(_ENGINE) as s:
        return set(s.exec(select(SessionRow.id)).all())


def task_exists(task_id: str) -> bool:
    with Session(_ENGINE) as s:
        return s.get(TaskRow, task_id) is not None


# --- credentials ---


def upsert_credential(session_id: str, domain: str, data_encrypted: bytes) -> CredentialRow:
    with Session(_ENGINE) as s:
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
    with Session(_ENGINE) as s:
        return list(
            s.exec(select(CredentialRow).where(CredentialRow.session_id == session_id)).all()
        )


def delete_credential(session_id: str, domain: str) -> bool:
    with Session(_ENGINE) as s:
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


def create_approval(
    task_id: str,
    reason: str,
    url: str | None = None,
    details: str | None = None,
) -> ApprovalRow:
    with Session(_ENGINE) as s:
        row = ApprovalRow(task_id=task_id, reason=reason, url=url, details=details)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def get_approval_status(approval_id: str) -> str | None:
    with Session(_ENGINE) as s:
        row = s.get(ApprovalRow, approval_id)
        return row.status if row else None


def get_approval(approval_id: str) -> ApprovalRow | None:
    with Session(_ENGINE) as s:
        return s.get(ApprovalRow, approval_id)


def list_approvals(
    status: str | None = "pending", task_id: str | None = None
) -> list[ApprovalRow]:
    with Session(_ENGINE) as s:
        q = select(ApprovalRow)
        if status:
            q = q.where(ApprovalRow.status == status)
        if task_id:
            q = q.where(ApprovalRow.task_id == task_id)
        return list(s.exec(q.order_by(ApprovalRow.created_at.desc())).all())  # type: ignore[attr-defined]


def pending_approval_for_task(task_id: str) -> ApprovalRow | None:
    with Session(_ENGINE) as s:
        return s.exec(
            select(ApprovalRow).where(
                ApprovalRow.task_id == task_id, ApprovalRow.status == "pending"
            )
        ).first()


def has_denied_approval(task_id: str) -> bool:
    with Session(_ENGINE) as s:
        return (
            s.exec(
                select(ApprovalRow.id).where(
                    ApprovalRow.task_id == task_id, ApprovalRow.status == "denied"
                )
            ).first()
            is not None
        )


def resolve_approval(approval_id: str, status: str) -> ApprovalRow | None:
    with Session(_ENGINE) as s:
        row = s.get(ApprovalRow, approval_id)
        if not row or row.status != "pending":
            return None
        row.status = status
        row.resolved_at = utcnow()
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


# --- api keys ---


def seed_api_keys(keys: list[str]) -> int:
    """Hash+upsert plaintext keys (env seed). Idempotent. Returns count added."""
    from cortex.auth import hash_key

    added = 0
    with Session(_ENGINE) as s:
        for key in (k.strip() for k in keys if k.strip()):
            h = hash_key(key)
            if s.exec(select(ApiKeyRow).where(ApiKeyRow.key_hash == h)).first():
                continue
            s.add(ApiKeyRow(label="env:seeded", key_hash=h, prefix=key[:8]))
            added += 1
        s.commit()
    if added:
        logger.info("Seeded %d API key(s) from environment", added)
    return added


def authenticate_key(key: str | None) -> ApiKeyRow | None:
    if not key:
        return None
    from cortex.auth import hash_key

    with Session(_ENGINE) as s:
        row = s.exec(select(ApiKeyRow).where(ApiKeyRow.key_hash == hash_key(key))).first()
        if row and not row.disabled:
            return row
        return None


def consume_key(key_id: str) -> bool:
    """Increment the daily counter. False if over daily_limit."""
    today = utcnow().strftime("%Y-%m-%d")
    with Session(_ENGINE) as s:
        row = s.get(ApiKeyRow, key_id)
        if not row:
            return False
        if row.counter_day != today:
            row.counter_day = today
            row.requests_today = 0
        if row.daily_limit is not None and row.requests_today >= row.daily_limit:
            s.add(row)
            s.commit()
            return False
        row.requests_today += 1
        row.last_used_at = utcnow()
        s.add(row)
        s.commit()
        return True


def create_api_key(label: str, daily_limit: int | None = None) -> tuple[ApiKeyRow, str]:
    """Returns (row, plaintext_key) — plaintext is never stored."""
    from cortex.auth import generate_key, hash_key

    key = generate_key()
    with Session(_ENGINE) as s:
        row = ApiKeyRow(
            label=label, key_hash=hash_key(key), prefix=key[:8], daily_limit=daily_limit
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row, key


def list_api_keys() -> list[ApiKeyRow]:
    with Session(_ENGINE) as s:
        return list(s.exec(select(ApiKeyRow)).all())


def disable_api_key(key_id: str) -> bool:
    with Session(_ENGINE) as s:
        row = s.get(ApiKeyRow, key_id)
        if not row:
            return False
        row.disabled = True
        s.add(row)
        s.commit()
        return True
