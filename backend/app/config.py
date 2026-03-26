import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings

_here = Path(__file__).parent.parent  # backend/
_env_file = os.environ.get("ENV_FILE", ".env")


class Settings(BaseSettings):
    DATABASE_URL: str = f"sqlite+aiosqlite:///{_here / 'otaki.db'}"

    SECRET_KEY: str = "dev-secret-key-change-in-production"

    DEFAULT_POLL_DAYS: int = 7

    SETUP_COMPLETE: bool = False

    SUWAYOMI_URL: str | None = None
    SUWAYOMI_USERNAME: str | None = None
    SUWAYOMI_PASSWORD: str | None = None
    SUWAYOMI_DOWNLOAD_PATH: str | None = None
    LIBRARY_PATH: str | None = None

    CHAPTER_NAMING_FORMAT: str = "{title}/{title} - Ch.{chapter}.cbz"
    RELOCATION_STRATEGY: Literal["auto", "hardlink", "copy", "move"] = "auto"
    DOWNLOAD_POLL_FALLBACK_SECONDS: int = 60
    MAX_RECONNECT_ATTEMPTS: int = 5
    MAX_DOWNLOAD_RETRIES: int = 2

    model_config = {"env_file": _env_file, "env_file_encoding": "utf-8"}


settings = Settings()
