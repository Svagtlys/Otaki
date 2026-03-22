import os
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app

_env_test_path = Path(__file__).parent.parent.parent / ".env.test"
_env_test = dotenv_values(_env_test_path) if _env_test_path.exists() else {}


def _get(key: str) -> str | None:
    return _env_test.get(key) or os.environ.get(key)


@pytest.fixture
def suwayomi_credentials():
    url = _get("SUWAYOMI_URL")
    if not url:
        pytest.skip("SUWAYOMI_URL not configured in .env.test")
    return {
        "url": url,
        "username": _get("SUWAYOMI_USERNAME") or "",
        "password": _get("SUWAYOMI_PASSWORD") or "",
    }


@pytest.fixture
def path_config(tmp_path):
    download = _get("SUWAYOMI_DOWNLOAD_PATH")
    library = _get("LIBRARY_PATH")

    if download:
        download_path = Path(download)
    else:
        download_path = tmp_path / "downloads"
        download_path.mkdir()

    if library:
        library_path = Path(library)
    else:
        library_path = tmp_path / "library"
        library_path.mkdir()

    return {"download_path": str(download_path), "library_path": str(library_path)}


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(settings, "SUWAYOMI_URL", None)
    monkeypatch.setattr(settings, "SUWAYOMI_USERNAME", None)
    monkeypatch.setattr(settings, "SUWAYOMI_PASSWORD", None)
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", None)
    monkeypatch.setattr(settings, "LIBRARY_PATH", None)
    monkeypatch.setattr("app.api.setup._write_env", lambda key, value: None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
