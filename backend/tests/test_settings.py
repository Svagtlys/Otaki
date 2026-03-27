"""Unit and integration tests for GET/PATCH /api/settings (issue #16)."""

import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings


# ---------------------------------------------------------------------------
# Unit tests — no live Suwayomi required
# ---------------------------------------------------------------------------


async def test_get_returns_current_values(logged_in_client, monkeypatch):
    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")
    monkeypatch.setattr(settings, "SUWAYOMI_USERNAME", "admin")
    monkeypatch.setattr(settings, "SUWAYOMI_PASSWORD", None)
    monkeypatch.setattr(settings, "DEFAULT_POLL_DAYS", 7)
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "auto")

    r = await logged_in_client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["suwayomi_url"] == "https://suwayomi.example.com"
    assert data["suwayomi_username"] == "admin"
    assert data["default_poll_days"] == 7
    assert data["chapter_naming_format"] == "{title}/{title} - Ch.{chapter}.cbz"
    assert data["relocation_strategy"] == "auto"


async def test_get_masks_password(logged_in_client, monkeypatch):
    monkeypatch.setattr(settings, "SUWAYOMI_PASSWORD", "supersecret")
    r = await logged_in_client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["suwayomi_password"] == "**masked**"


async def test_get_password_none_when_unset(logged_in_client, monkeypatch):
    monkeypatch.setattr(settings, "SUWAYOMI_PASSWORD", None)
    r = await logged_in_client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["suwayomi_password"] is None


async def test_get_unauthenticated_returns_401(auth_client):
    r = await auth_client.get("/api/settings")
    assert r.status_code == 401


async def test_patch_unauthenticated_returns_401(auth_client):
    r = await auth_client.patch("/api/settings", json={"default_poll_days": 14})
    assert r.status_code == 401


async def test_patch_updates_in_memory(logged_in_client, monkeypatch):
    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "write_env", lambda key, value: setattr(settings, key, value))

    r = await logged_in_client.patch("/api/settings", json={"default_poll_days": 14})
    assert r.status_code == 200
    assert r.json()["default_poll_days"] == 14
    assert settings.DEFAULT_POLL_DAYS == 14


async def test_patch_calls_write_env(logged_in_client, monkeypatch):
    from app.api import settings as settings_api

    calls: list[tuple[str, str]] = []

    def fake_write_env(key, value):
        calls.append((key, value))
        setattr(settings, key, value)

    monkeypatch.setattr(settings_api, "write_env", fake_write_env)

    await logged_in_client.patch("/api/settings", json={"chapter_naming_format": "{title}.cbz"})

    assert ("CHAPTER_NAMING_FORMAT", "{title}.cbz") in calls


async def test_patch_partial_update(logged_in_client, monkeypatch):
    from app.api import settings as settings_api

    original_poll = settings.DEFAULT_POLL_DAYS
    monkeypatch.setattr(settings_api, "write_env", lambda key, value: setattr(settings, key, value))

    r = await logged_in_client.patch("/api/settings", json={"chapter_naming_format": "{title}.cbz"})
    assert r.status_code == 200
    assert r.json()["default_poll_days"] == original_poll


async def test_patch_invalid_directory_returns_400(logged_in_client, monkeypatch):
    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "validate_path", lambda p: False)

    r = await logged_in_client.patch("/api/settings", json={"library_path": "/nonexistent/path"})
    assert r.status_code == 400
    assert "library_path" in r.json()["detail"]


async def test_patch_no_ping_when_suwayomi_fields_not_changed(logged_in_client, monkeypatch):
    from app.api import settings as settings_api

    ping_called = False

    async def fake_validate_suwayomi(*args):
        nonlocal ping_called
        ping_called = True
        return False  # would fail if called

    monkeypatch.setattr(settings_api, "validate_suwayomi", fake_validate_suwayomi)
    monkeypatch.setattr(settings_api, "write_env", lambda key, value: setattr(settings, key, value))

    r = await logged_in_client.patch("/api/settings", json={"default_poll_days": 3})
    assert r.status_code == 200
    assert not ping_called


# ---------------------------------------------------------------------------
# Integration tests — require live Suwayomi
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_valid_suwayomi_credentials(logged_in_client, suwayomi_credentials, monkeypatch):
    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "write_env", lambda key, value: setattr(settings, key, value))

    r = await logged_in_client.patch("/api/settings", json={
        "suwayomi_url": suwayomi_credentials["url"],
        "suwayomi_username": suwayomi_credentials["username"],
        "suwayomi_password": suwayomi_credentials["password"],
    })
    assert r.status_code == 200


@pytest.mark.integration
async def test_patch_invalid_suwayomi_credentials_returns_400(logged_in_client, suwayomi_credentials, monkeypatch):
    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "write_env", lambda key, value: setattr(settings, key, value))
    monkeypatch.setattr(settings, "SUWAYOMI_URL", suwayomi_credentials["url"])

    r = await logged_in_client.patch("/api/settings", json={"suwayomi_password": "wrong-password"})
    assert r.status_code == 400
    assert "Could not connect to Suwayomi" in r.json()["detail"]
