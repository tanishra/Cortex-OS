import logging
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

logger = logging.getLogger("cortex.config")

ENV_PROFILE = os.environ.get("ENV_PROFILE", "dev")


def _env_files() -> tuple[Path, ...]:
    """Load order: .env (secrets/base) then .env.{profile} (non-secret overrides)."""
    files: list[Path] = [BASE_DIR / ".env"]
    profile = BASE_DIR / f".env.{ENV_PROFILE}"
    if profile.exists():
        files.append(profile)
    elif ENV_PROFILE != "dev":
        logger.warning("ENV_PROFILE=%s but %s not found", ENV_PROFILE, profile.name)
    return tuple(files)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_files(), extra="ignore")

    environment: str = ENV_PROFILE
    debug: bool = True

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"

    redis_url: str = "redis://localhost:6379"
    database_url: str = f"sqlite:///{BASE_DIR / 'cortex.db'}"

    artifacts_dir: Path = BASE_DIR / "artifacts"
    browser_profiles_dir: Path = BASE_DIR / "profiles"
    browser_headless: bool = True
    browser_chromium_sandbox: bool = True  # false inside unprivileged containers

    max_steps: int = 100
    task_timeout_s: int = 600
    step_timeout_s: int = 180
    worker_concurrency: int = 2
    task_max_retries: int = 4  # total attempts including the first
    task_retry_base_s: float = 2.0  # backoff: base * 2^(attempt-1), capped at 60s
    max_queued_tasks: int = 100  # POST /tasks → 429 when arq backlog exceeds this
    backpressure_retry_after_s: int = 30
    # 0 = off; min seconds between task starts per start_url host
    rate_limit_per_domain_s: float = 0.0
    # OTLP/HTTP base, e.g. http://jaeger:4318 — empty = tracing off
    otel_exporter_otlp_endpoint: str = ""
    task_max_tokens: int = 0  # 0 = off; default per-task token budget
    task_latency_budget_s: float = 0.0  # 0 = off; flag tasks slower than this
    openai_fallback_model: str = ""  # fallback_llm for browser-use; empty = none

    require_api_key: bool = False
    api_keys: str = ""  # comma-separated

    vault_fernet_key: str = ""  # P1 — credential vault
    human_notify_url: str = ""  # P2 — escalation webhook
    session_open_timeout_s: int = 600  # max duration of a headed login browser
    session_ttl_s: int = 604800  # 7 days; new sessions expire after this
    session_queue_name: str = "arq:queue:sessions"  # dedicated lane for login jobs

    # pluggable backends (ports registry)
    artifact_backend: str = "fs"  # fs | s3
    secrets_backend: str = "fernet"
    queue_backend: str = "arq"

    # s3 artifact backend (only used when artifact_backend=s3)
    s3_bucket: str = "cortex-artifacts"
    s3_endpoint_url: str | None = None  # e.g. http://localhost:9000 for MinIO
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"


settings = Settings()
