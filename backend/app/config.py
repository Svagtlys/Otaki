from pathlib import Path

from pydantic_settings import BaseSettings

_here = Path(__file__).parent.parent  # backend/


class Settings(BaseSettings):
    DATABASE_URL: str = f"sqlite+aiosqlite:///{_here / 'otaki.db'}"

    SECRET_KEY: str = "dev-secret-key-change-in-production"

    SUWAYOMI_URL: str | None = None
    SUWAYOMI_USERNAME: str | None = None
    SUWAYOMI_PASSWORD: str | None = None
    SUWAYOMI_DOWNLOAD_PATH: str | None = None
    LIBRARY_PATH: str | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
