import logging

from fastapi import APIRouter, HTTPException, Request

from cortex.models import ApprovalDecision, ApprovalResponse, ErrorResponse
from cortex.store import db
from cortex.store.db import ApprovalRow

logger = logging.getLogger("cortex.api.approvals")
router = APIRouter(prefix="/approvals", tags=["approvals"])


def _to_response(row: ApprovalRow) -> ApprovalResponse:
    return ApprovalResponse(
        id=row.id,
        task_id=row.task_id,
        reason=row.reason,
        url=row.url,
        status=row.status,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


@router.get("", response_model=list[ApprovalResponse])
async def list_approvals(pending: bool = True) -> list[ApprovalResponse]:
    return [_to_response(r) for r in db.list_approvals("pending" if pending else None)]


@router.post(
    "/{approval_id}/respond",
    response_model=ApprovalResponse,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def respond_approval(
    approval_id: str, decision: ApprovalDecision, request: Request
) -> ApprovalResponse:
    row = db.resolve_approval(approval_id, "approved" if decision.approve else "denied")
    if not row:
        raise HTTPException(status_code=404, detail="approval not found or already resolved")
    queue = request.app.state.arq
    if queue is None:
        raise HTTPException(status_code=503, detail="queue unavailable")
    await queue.enqueue_job("approval_response_job", row.task_id, decision.approve)
    logger.info(
        "Approval %s for task %s: %s",
        approval_id,
        row.task_id,
        "approved" if decision.approve else "denied",
    )
    return _to_response(row)
