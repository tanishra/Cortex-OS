import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from cortex.models import ErrorResponse
from cortex.store import artifacts, db

logger = logging.getLogger("cortex.api.artifacts")
router = APIRouter(prefix="/tasks/{task_id}", tags=["artifacts"])


@router.get("/steps", responses={404: {"model": ErrorResponse}})
async def get_steps(task_id: str) -> list[dict]:
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="task not found")
    return artifacts.list_steps(task_id)


@router.get("/replay", responses={404: {"model": ErrorResponse}})
async def get_replay(task_id: str) -> dict:
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="task not found")
    replay = artifacts.get_replay(task_id)
    if replay is None:
        raise HTTPException(status_code=404, detail="no replay recorded yet")
    return replay


@router.get("/screenshots/{filename}", responses={404: {"model": ErrorResponse}})
async def get_screenshot(task_id: str, filename: str) -> FileResponse:
    path = artifacts.get_screenshot_path(task_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(path, media_type="image/png")
