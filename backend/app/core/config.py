"""Local-first settings for the V1.07 adaptation of the FastAPI template."""
from pathlib import Path
from pydantic import Field, field_validator
from urllib.parse import urlsplit
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_ignore_empty=True, extra="ignore")
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = Field(min_length=32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    PROJECT_NAME: str = "监测工作台 V1.07"
    DATABASE_URL: str = "sqlite:///" + (ROOT / "data" / "monitoring.db").as_posix()
    STORAGE_DIR: Path = ROOT / "data" / "projects"
    FRONTEND_HOST: str = "http://localhost:5173"
    PUBLIC_BASE_URL: str = ""
    WEB_BIND_HOST: str = "127.0.0.1"
    FIRST_SUPERUSER: str = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = Field(min_length=12)
    AI_BASE_URL: str = ""
    AI_MODEL: str = ""
    AI_API_KEY: str = ""
    AI_TIMEOUT: int = Field(default=90, ge=1, le=300)

    @field_validator("PUBLIC_BASE_URL")
    @classmethod
    def public_origin(cls, value):
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path or "\\" in value or any(ord(c) < 32 for c in value)):
            raise ValueError("PUBLIC_BASE_URL 必须为不含账号、路径或参数的网站地址，如 https://monitor.example.com")
        _ = parsed.port
        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def postgres_driver(cls, value):
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

settings = Settings()
