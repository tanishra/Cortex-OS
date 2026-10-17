import logging

from fastapi import APIRouter, HTTPException, Response

from cortex.models import ErrorResponse
from cortex.store import artifacts, db

logger = logging.getLogger("cortex.api.artifacts")
router = APIRouter(prefix="/tasks/{task_id}", tags=["artifacts"])


@router.get("/steps", responses={404: {"model": ErrorResponse}})
async def get_steps(task_id: str) -> list[dict]:
    if not await db.arun(db.get_task, task_id):
        raise HTTPException(status_code=404, detail="task not found")
    return await artifacts.list_steps(task_id)


@router.get("/replay", responses={404: {"model": ErrorResponse}})
async def get_replay(task_id: str) -> dict:
    if not await db.arun(db.get_task, task_id):
        raise HTTPException(status_code=404, detail="task not found")
    replay = await artifacts.get_replay(task_id)
    if replay is None:
        raise HTTPException(status_code=404, detail="no replay recorded yet")
    return replay


@router.get("/screenshots/{filename}", responses={404: {"model": ErrorResponse}})
async def get_screenshot(task_id: str, filename: str) -> Response:
    png = await artifacts.get_screenshot(task_id, filename)
    if png is None:
        raise HTTPException(status_code=404, detail="screenshot not found")
    return Response(content=png, media_type="image/png")
