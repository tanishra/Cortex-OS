import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import cortex.store.artifacts_s3  # noqa: F401 — registers the s3 artifact backend
import cortex.store.queue  # noqa: F401 — registers the arq queue backend
from cortex.api import (
    routes_admin,
    routes_approvals,
    routes_artifacts,
    routes_sessions,
    routes_stats,
    routes_tasks,
)
from cortex.config import settings
from cortex.logging import setup_logging
from cortex.ports.registry import get_backend
from cortex.store import db
from cortex.store.db import init_db
from cortex.store.queue import NullJobQueue
from cortex.telemetry import init_tracing, shutdown_tracing

setup_logging()
logger = logging.getLogger("cortex.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db.seed_api_keys(settings.api_keys.split(","))
    init_tracing("cortex-api", settings.otel_exporter_otlp_endpoint)
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    queue = get_backend("queue")
    await queue.connect()
    app.state.queue = queue if queue.available() else NullJobQueue()
    yield
    await app.state.queue.aclose()
    await shutdown_tracing()


app = FastAPI(
    title="Cortex-OS",
    description=(
        "Production-grade browser agent service — submit tasks in plain English, "
        "executed by browser-use with sessions, approvals, retries, and audit events."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "tasks", "description": "Submit, inspect, cancel, and audit browser tasks."},
        {"name": "artifacts", "description": "Step JSON, screenshots, and replay data per task."},
        {"name": "sessions", "description": "Named profiles w/ login + credential vault."},
        {"name": "approvals", "description": "Human-in-the-loop gates for domains and actions."},
        {"name": "admin", "description": "API-key lifecycle (create, list, revoke)."},
        {"name": "ops", "description": "Health, readiness, and aggregate stats."},
    ],
)

app.include_router(routes_tasks.router)
app.include_router(routes_artifacts.router)
app.include_router(routes_sessions.router)
app.include_router(routes_approvals.router)
app.include_router(routes_admin.router)
app.include_router(routes_stats.router)

PUBLIC_PATHS = {"/health", "/ready", "/docs", "/openapi.json", "/redoc"}


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    """Optional API-key gate. Enabled via REQUIRE_API_KEY=true + hashed key rows."""
    if settings.require_api_key and request.url.path not in PUBLIC_PATHS:
        row = await db.arun(db.authenticate_key, request.headers.get("x-api-key"))
        if not row:
            return JSONResponse(status_code=401, content={"detail": "invalid api key"})
        if not await db.arun(db.consume_key, row.id):
            return JSONResponse(status_code=429, content={"detail": "daily_limit reached"})
        request.state.api_key_id = row.id
    return await call_next(request)


@app.get("/health", tags=["ops"], summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready", tags=["ops"], summary="Readiness probe (includes queue availability)")
async def ready() -> dict:
    return {"status": "ready", "queue": app.state.queue.available()}
