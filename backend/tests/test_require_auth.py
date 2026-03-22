"""Integration tests for auth middleware and require_auth dependency (issue #12).

Uses a minimal test route mounted on the app to exercise the middleware
without depending on any not-yet-implemented routers.
"""

import pytest
import pytest_asyncio
from fastapi import Depends
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.api.auth import UserResponse, require_auth
from app.config import settings
from app.main import app
from app.models.user import User


@pytest_asyncio.fixture
async def auth_client(monkeypatch):
    """Client with setup already complete (SUWAYOMI_URL set)."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_session = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", test_session)

    async with test_engine.begin() as conn:
        from app import models  # noqa: F401
        await conn.run_sync(database.Base.metadata.create_all)

    # All settings populated → setup middleware passes for all routes
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


@pytest.fixture(autouse=True)
def protected_route():
    """Mount a temporary protected route for the duration of each test."""

    async def _handler(user: User = Depends(require_auth)) -> UserResponse:
        return UserResponse(id=user.id, username=user.username)

    route = APIRoute("/api/test/protected", _handler, methods=["GET"])
    app.router.routes.append(route)
    yield
    app.router.routes.remove(route)


@pytest.fixture
def admin_credentials():
    return {"username": "admin", "password": "s3cr3tpassword!"}


async def _login(client, credentials):
    await client.post("/api/setup/user", json=credentials)
    r = await client.post("/api/auth/login", json=credentials)
    return r.json()["access_token"]


async def test_protected_route_no_token(auth_client):
    r = await auth_client.get("/api/test/protected")
    assert r.status_code == 401
    assert r.json()["detail"] == "Not authenticated"


async def test_protected_route_invalid_token(auth_client):
    r = await auth_client.get(
        "/api/test/protected", headers={"Authorization": "Bearer not-a-token"}
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"


async def test_protected_route_valid_bearer(auth_client, admin_credentials):
    token = await _login(auth_client, admin_credentials)
    r = await auth_client.get(
        "/api/test/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["username"] == admin_credentials["username"]


async def test_protected_route_valid_cookie(auth_client, admin_credentials):
    token = await _login(auth_client, admin_credentials)
    auth_client.cookies.set("otaki_session", token)
    r = await auth_client.get("/api/test/protected")
    auth_client.cookies.delete("otaki_session")
    assert r.status_code == 200


async def test_setup_routes_exempt(auth_client):
    """Setup routes must not require auth — middleware 401 has detail 'Not authenticated'."""
    r = await auth_client.post(
        "/api/setup/user", json={"username": "admin", "password": "password123"}
    )
    assert r.status_code == 200


async def test_auth_routes_exempt(auth_client):
    """Auth routes must not require auth — middleware 401 has a different detail."""
    r = await auth_client.post(
        "/api/auth/login", json={"username": "nobody", "password": "x"}
    )
    # Route handler returns "Invalid credentials", not middleware's "Not authenticated"
    assert r.json().get("detail") != "Not authenticated"
