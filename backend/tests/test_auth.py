"""Integration tests for local login (issue #8).

No live Suwayomi instance needed — all tests use the in-process ASGI client
with an in-memory SQLite database.
"""

import pytest


@pytest.fixture
def admin_credentials():
    return {"username": "admin", "password": "s3cr3tpassword!"}


async def test_create_user(client, admin_credentials):
    r = await client.post("/api/setup/user", json=admin_credentials)
    assert r.status_code == 200


async def test_create_user_duplicate(client, admin_credentials):
    await client.post("/api/setup/user", json=admin_credentials)
    r = await client.post("/api/setup/user", json=admin_credentials)
    assert r.status_code == 409
    assert r.json()["detail"] == "Admin user already exists"


async def test_login_success(client, admin_credentials):
    await client.post("/api/setup/user", json=admin_credentials)
    r = await client.post("/api/auth/login", json=admin_credentials)
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_login_wrong_password(client, admin_credentials):
    await client.post("/api/setup/user", json=admin_credentials)
    r = await client.post(
        "/api/auth/login",
        json={**admin_credentials, "password": "wrongpassword"},
    )
    assert r.status_code == 401


async def test_login_unknown_user(client):
    r = await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "password"},
    )
    assert r.status_code == 401


async def test_me_authenticated(client, admin_credentials):
    await client.post("/api/setup/user", json=admin_credentials)
    login = await client.post("/api/auth/login", json=admin_credentials)
    token = login.json()["access_token"]

    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == admin_credentials["username"]
    assert "id" in body


async def test_me_no_token(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_invalid_token(client):
    r = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert r.status_code == 401


async def test_logout(client, admin_credentials):
    await client.post("/api/setup/user", json=admin_credentials)
    login = await client.post("/api/auth/login", json=admin_credentials)
    token = login.json()["access_token"]

    r = await client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
