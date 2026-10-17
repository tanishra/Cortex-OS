import logging

from fastapi import APIRouter, HTTPException

from cortex.models import ApiKeyCreate, ApiKeyCreated, ApiKeyInfo, ErrorResponse
from cortex.store import db
from cortex.store.db import ApiKeyRow

logger = logging.getLogger("cortex.api.admin")
router = APIRouter(prefix="/admin/keys", tags=["admin"])


def _info(row: ApiKeyRow) -> ApiKeyInfo:
    return ApiKeyInfo(
        id=row.id,
        label=row.label,
        prefix=row.prefix,
        daily_limit=row.daily_limit,
        requests_today=row.requests_today,
        disabled=row.disabled,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_key(req: ApiKeyCreate) -> ApiKeyCreated:
    """Mint a key. The plaintext is returned here and never stored."""
    row, key = await db.arun(db.create_api_key, req.label, req.daily_limit)
    logger.info("API key created: %s (%s)", row.label, row.prefix)
    return ApiKeyCreated(id=row.id, label=row.label, key=key)


@router.get("", response_model=list[ApiKeyInfo])
async def list_keys() -> list[ApiKeyInfo]:
    rows = await db.arun(db.list_api_keys)
    return [_info(r) for r in rows]


@router.delete(
    "/{key_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
)
async def revoke_key(key_id: str) -> None:
    if not await db.arun(db.disable_api_key, key_id):
        raise HTTPException(status_code=404, detail="key not found")
    logger.info("API key revoked: %s", key_id)
