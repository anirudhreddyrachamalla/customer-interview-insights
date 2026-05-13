"""Application settings loaded from environment / repo-root .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root is two levels above this file: backend/app/config.py -> backend -> repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Runtime configuration for the FastAPI service.

    Values are read from environment variables, with a fallback to the
    repo-root ``.env`` file. Unknown keys are ignored so the same ``.env``
    can host both frontend and backend variables.
    """

    database_url: str
    assemblyai_api_key: str = ""
    anthropic_api_key: str = ""
    audio_storage_dir: Path = Path("storage/audio")

    @field_validator("database_url")
    @classmethod
    def _ensure_async_pg_driver(cls, v: str) -> str:
        # Render injects DATABASE_URL with the bare `postgres://` scheme,
        # but SQLAlchemy's async engine needs the driver named explicitly.
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` instance.

    Cached so repeated calls reuse the same object (and the same parsed
    ``.env``). Tests can clear the cache with ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]
