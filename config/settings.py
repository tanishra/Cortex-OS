from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    raise RuntimeError("Missing .env file in project root")


class LiveKitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIVEKIT_")
    url: str
    api_key: str
    api_secret: str


class OpenAISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENAI_")
    api_key: str
    model: str = "gpt-4o-mini-realtime-preview"


class GmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GMAIL_")
    user: str
    app_password: str


class AppSettings(BaseModel):
    environment: str = "development"
    debug: bool = True

    livekit: LiveKitSettings = Field(default_factory=LiveKitSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    gmail: GmailSettings = Field(default_factory=GmailSettings)


def load_settings() -> AppSettings:
    try:
        return AppSettings()
    except ValidationError as e:
        raise RuntimeError(f"Invalid environment configuration:\n{e}")


settings = load_settings()