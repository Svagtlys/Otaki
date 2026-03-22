import os
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.config import settings
from app.main import app


@pytest_asyncio.fixture
async def db_session():
    """Bare async DB session backed by in-memory SQLite. For service-layer tests
    that call functions directly without going through the HTTP API."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        from app import models  # noqa: F401
        await conn.run_sync(database.Base.metadata.create_all)
    async with session_factory() as session:
        yield session
    await engine.dispose()

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
def suwayomi_settings(suwayomi_credentials, monkeypatch):
    """Skips if Suwayomi is not configured, and patches settings so that
    suwayomi.py service functions can connect without going through the API."""
    monkeypatch.setattr(settings, "SUWAYOMI_URL", suwayomi_credentials["url"])
    monkeypatch.setattr(settings, "SUWAYOMI_USERNAME", suwayomi_credentials["username"])
    monkeypatch.setattr(settings, "SUWAYOMI_PASSWORD", suwayomi_credentials["password"])


@pytest.fixture
def test_manga_title():
    """A manga title known to exist on the configured Suwayomi instance.
    Set TEST_MANGA_TITLE in .env.test; defaults to 'a' if omitted."""
    return _get("TEST_MANGA_TITLE") or "a"


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
async def auth_client(monkeypatch):
    """HTTP client with setup complete and all settings populated.
    Use this for tests that need to hit authenticated routes without
    going through the setup wizard."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_session = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", test_session)

    async with test_engine.begin() as conn:
        from app import models  # noqa: F401
        await conn.run_sync(database.Base.metadata.create_all)

    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")
    monkeypatch.setattr(settings, "SUWAYOMI_USERNAME", None)
    monkeypatch.setattr(settings, "SUWAYOMI_PASSWORD", None)
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", "/tmp")
    monkeypatch.setattr(settings, "LIBRARY_PATH", "/tmp")
    monkeypatch.setattr("app.api.setup._write_env", lambda key, value: None)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    await test_engine.dispose()


@pytest_asyncio.fixture
async def logged_in_client(auth_client):
    """auth_client with a valid JWT already set as a Bearer token.
    Use this for tests that need to hit authenticated routes."""
    await auth_client.post(
        "/api/setup/user", json={"username": "admin", "password": "testpassword!"}
    )
    r = await auth_client.post(
        "/api/auth/login", json={"username": "admin", "password": "testpassword!"}
    )
    token = r.json()["access_token"]
    auth_client.headers = {**auth_client.headers, "Authorization": f"Bearer {token}"}
    return auth_client


@pytest_asyncio.fixture
async def client(monkeypatch):
    # Use a fresh in-memory SQLite DB for each test — avoids lifespan dependency
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_session = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", test_session)

    async with test_engine.begin() as conn:
        from app import models  # noqa: F401 — registers models on Base.metadata
        await conn.run_sync(database.Base.metadata.create_all)

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

    await test_engine.dispose()
