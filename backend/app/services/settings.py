from pathlib import Path

from ..config import settings
from . import suwayomi


def write_env(key: str, value) -> None:
    """Write a key/value to .env and update the in-memory settings object."""
    import os

    from dotenv import set_key

    env_file = os.environ.get("ENV_FILE", ".env")
    set_key(env_file, key, str(value))
    setattr(settings, key, value)


def validate_path(path: str) -> bool:
    """Return True if path exists and is a directory."""
    return Path(path).is_dir()


async def validate_suwayomi(url: str, username: str | None, password: str | None) -> bool:
    """Return True if Suwayomi is reachable with the given credentials."""
    return await suwayomi.ping(url, username or "", password or "")
