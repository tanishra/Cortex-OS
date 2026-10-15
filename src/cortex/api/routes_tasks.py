import logging

from fastapi import APIRouter, HTTPException, Request

from cortex.models import ErrorResponse, TaskRequest, TaskResponse, TaskStatus
from cortex.store import db
from cortex.store.db import TaskRow

logger = logging.getLogger("cortex.api.tasks")
router = APIRouter(prefix="/tasks", tags=["tasks"])


def _to_response(row: TaskRow) -> TaskResponse:
    return TaskResponse(
        id=row.id,
        status=TaskStatus(row.status),
        task=row.task,
        result=row.result,
        error=row.error,
        steps_taken=row.steps_taken,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "",
    response_model=TaskResponse,
    status_code=202,
    responses={400: {"model": ErrorResponse}},
)
async def create_task(req: TaskRequest, request: Request) -> TaskResponse:
    row, created = await db.arun(db.create_task, req)
    if created:
        queue = request.app.state.queue
        if await queue.enqueue("run_task_job", row.id):
            logger.info("Enqueued task %s", row.id)
        else:
            logger.warning("No queue configured; task %s created but not enqueued", row.id)
    return _to_response(row)


@router.get("", response_model=list[TaskResponse])
async def get_tasks(limit: int = 50, offset: int = 0) -> list[TaskResponse]:
    rows = await db.arun(db.list_tasks, limit=limit, offset=offset)
    return [_to_response(r) for r in rows]


@router.get("/{task_id}", response_model=TaskResponse, responses={404: {"model": ErrorResponse}})
async def get_task(task_id: str) -> TaskResponse:
    row = await db.arun(db.get_task, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    return _to_response(row)


@router.post(
    "/{task_id}/cancel",
    response_model=TaskResponse,
    responses={404: {"model": ErrorResponse}},
)
async def cancel_task(task_id: str) -> TaskResponse:
    row = await db.arun(db.get_task, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    if row.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
        return _to_response(row)
    if row.status == TaskStatus.QUEUED:
        row = await db.arun(
            db.update_task,
            task_id,
            status=TaskStatus.CANCELLED,
            error="cancelled before start",
        )
    else:
        row = await db.arun(db.request_cancel, task_id)
    return _to_response(row)  # type: ignore[arg-type]


@router.post(
    "/{task_id}/resume",
    response_model=TaskResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def resume_task(task_id: str, request: Request) -> TaskResponse:
    """Resume a task paused in waiting_human after human intervention."""
    row = await db.arun(db.get_task, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    if row.status != TaskStatus.WAITING_HUMAN:
        raise HTTPException(
            status_code=409, detail=f"task is {row.status}, not waiting_human"
        )
    if not await request.app.state.queue.enqueue("human_resume_job", task_id):
        raise HTTPException(status_code=503, detail="queue unavailable")
    return _to_response(row)
