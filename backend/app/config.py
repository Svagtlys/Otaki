from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./otaki.db"

    SUWAYOMI_URL: str | None = None
    SUWAYOMI_USERNAME: str | None = None
    SUWAYOMI_PASSWORD: str | None = None
    SUWAYOMI_DOWNLOAD_PATH: str | None = None
    LIBRARY_PATH: str | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
