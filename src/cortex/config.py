from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    environment: str = "development"
    debug: bool = True

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"

    redis_url: str = "redis://localhost:6379"
    database_url: str = f"sqlite:///{BASE_DIR / 'cortex.db'}"

    artifacts_dir: Path = BASE_DIR / "artifacts"
    browser_profiles_dir: Path = BASE_DIR / "profiles"
    browser_headless: bool = True

    max_steps: int = 100
    task_timeout_s: int = 600
    step_timeout_s: int = 180
    worker_concurrency: int = 2

    require_api_key: bool = False
    api_keys: str = ""  # comma-separated

    vault_fernet_key: str = ""  # P1 — credential vault
    human_notify_url: str = ""  # P2 — escalation webhook
    session_open_timeout_s: int = 600  # max duration of a headed login browser
    session_ttl_s: int = 604800  # 7 days; new sessions expire after this
    session_queue_name: str = "arq:queue:sessions"  # dedicated lane for login jobs

    # pluggable backends (ports registry)
    artifact_backend: str = "fs"
    secrets_backend: str = "fernet"
    queue_backend: str = "arq"


settings = Settings()
