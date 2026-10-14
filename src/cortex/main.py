import logging
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from cortex.api import routes_artifacts, routes_tasks
from cortex.config import settings
from cortex.logging import setup_logging
from cortex.store.db import init_db

setup_logging()
logger = logging.getLogger("cortex.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        logger.info("Connected to Redis at %s", settings.redis_url)
    except Exception:
        logger.warning("Redis unavailable — tasks will be created but not enqueued")
        app.state.arq = None
    yield
    if app.state.arq is not None:
        await app.state.arq.close()


app = FastAPI(
    title="Cortex-OS",
    description=(
        "Production-grade browser agent service — submit tasks in plain English, "
        "executed by browser-use."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(routes_tasks.router)
app.include_router(routes_artifacts.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    return {"status": "ready", "queue": app.state.arq is not None}
