from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "BooruRadar"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://booruradar:booruradar@localhost:5432/booruradar"
    http_timeout_seconds: float = Field(default=10.0, gt=0)
    danbooru_login: SecretStr | None = Field(
        default=None,
        validation_alias="DANBOORU_LOGIN",
        repr=False,
    )
    danbooru_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DANBOORU_API_KEY",
        repr=False,
    )
    worker_poll_interval_seconds: float = Field(default=60.0, gt=0)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BOORURADAR_",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("log_level must be a standard Python logging level")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
