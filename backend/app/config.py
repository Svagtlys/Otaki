import logging
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(f"otaki.{__name__}")

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
    SUWAYOMI_VERIFY_SSL: bool = True
    SUWAYOMI_DOWNLOAD_PATH: str | None = None
    LIBRARY_PATH: str | None = None
    COVERS_PATH: str = str(_here / "covers")
    WATERMARKS_PATH: str = str(_here / "watermarks")

    CHAPTER_NAMING_FORMAT: str = "{title}/{title} - Ch.{chapter}.cbz"
    RELOCATION_STRATEGY: Literal["auto", "hardlink", "copy", "move"] = "auto"
    DOWNLOAD_POLL_FALLBACK_SECONDS: int = 60
    MAX_RECONNECT_ATTEMPTS: int = 5
    MAX_DOWNLOAD_RETRIES: int = 2

    CHAPTER_FILE_NAME_REGEX: list[str] | None = None

    @field_validator("CHAPTER_FILE_NAME_REGEX", mode="after")
    @classmethod
    def validate_regex_patterns(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        for pattern in value:
            try:
                replaced = pattern.replace("{chapter_number}", "1")
                re.compile(replaced)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
        return value

    model_config = {"env_file": _env_file, "env_file_encoding": "utf-8"}


settings = Settings()
