import logging

from fastapi import APIRouter, HTTPException, Request

from cortex.models import (
    CredentialRequest,
    CredentialResponse,
    ErrorResponse,
    SessionCreate,
    SessionResponse,
)
from cortex.store import db
from cortex.store.db import CredentialRow, SessionRow
from cortex.vault import credentials

logger = logging.getLogger("cortex.api.sessions")
router = APIRouter(prefix="/sessions", tags=["sessions"])


def _to_response(row: SessionRow) -> SessionResponse:
    return SessionResponse(
        id=row.id, name=row.name, created_at=row.created_at, last_used_at=row.last_used_at
    )


def _cred_response(row: CredentialRow) -> CredentialResponse:
    return CredentialResponse(
        id=row.id, session_id=row.session_id, domain=row.domain, created_at=row.created_at
    )


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(req: SessionCreate) -> SessionResponse:
    existing = await db.arun(db.get_session_by_name, req.name)
    if existing:
        raise HTTPException(status_code=409, detail="session name already exists")
    return _to_response(await db.arun(db.create_session, req.name))


@router.get("", response_model=list[SessionResponse])
async def list_sessions() -> list[SessionResponse]:
    rows = await db.arun(db.list_sessions)
    return [_to_response(r) for r in rows]


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_session(session_id: str) -> SessionResponse:
    row = await db.arun(db.get_session, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="session not found")
    return _to_response(row)


@router.delete("/{session_id}", status_code=204, responses={404: {"model": ErrorResponse}})
async def delete_session(session_id: str) -> None:
    if not await db.arun(db.delete_session, session_id):
        raise HTTPException(status_code=404, detail="session not found")


@router.post(
    "/{session_id}/open",
    status_code=202,
    responses={404: {"model": ErrorResponse}},
)
async def open_session(session_id: str, request: Request) -> dict:
    """Open a headed browser on this session's profile so a human can log in."""
    if not await db.arun(db.get_session, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    queue = request.app.state.queue
    if not await queue.enqueue("open_session_job", session_id):
        raise HTTPException(status_code=503, detail="queue unavailable")
    return {"status": "opening", "session_id": session_id}


@router.post(
    "/{session_id}/close",
    status_code=202,
    responses={404: {"model": ErrorResponse}},
)
async def close_session(session_id: str) -> dict:
    row = await db.arun(db.get_session, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="session not found")
    await db.arun(db.update_session, session_id, close_requested=True)
    return {"status": "closing", "session_id": session_id}


# --- credentials ---


@router.post(
    "/{session_id}/credentials",
    response_model=CredentialResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def add_credentials(session_id: str, req: CredentialRequest) -> CredentialResponse:
    if not await db.arun(db.get_session, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    try:
        row = await db.arun(
            credentials.store_credentials, session_id, req.domain, req.fields
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _cred_response(row)


@router.get("/{session_id}/credentials", response_model=list[CredentialResponse])
async def list_credentials(session_id: str) -> list[CredentialResponse]:
    if not await db.arun(db.get_session, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = await db.arun(db.get_credentials_for_session, session_id)
    return [_cred_response(r) for r in rows]


@router.delete(
    "/{session_id}/credentials/{domain}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
)
async def delete_credential(session_id: str, domain: str) -> None:
    if not await db.arun(credentials.delete_credentials, session_id, domain):
        raise HTTPException(status_code=404, detail="credential not found")
