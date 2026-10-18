import logging

from fastapi import APIRouter, Request

from cortex.config import settings
from cortex.models import StatsResponse
from cortex.store import db

logger = logging.getLogger("cortex.api.stats")
router = APIRouter(tags=["ops"])


@router.get("/stats", response_model=StatsResponse)
async def get_stats(request: Request) -> StatsResponse:
    stats = await db.arun(db.task_stats)
    queue = request.app.state.queue
    stats["queue_depth"] = await queue.queue_depth()
    stats["session_queue_depth"] = await queue.queue_depth(settings.session_queue_name)
    return StatsResponse(**stats)
