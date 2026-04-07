"""Tests for GET /api/health (issue #110).

All tests are unit-style — no live Suwayomi required.
"""

import pytest
from datetime import datetime, timezone

from app.workers import download_listener, scheduler as scheduler_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_health(client):
    return await client.get("/api/health")


# ---------------------------------------------------------------------------
# Auth / accessibility
# ---------------------------------------------------------------------------


async def test_health_requires_no_auth(auth_client):
    """Health endpoint is accessible without a JWT."""
    r = await auth_client.get("/api/health")
    assert r.status_code == 200


async def test_health_accessible_before_setup(client):
    """Health endpoint works even before setup is complete (SETUP_COMPLETE=False)."""
    r = await client.get("/api/health")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


async def test_health_response_shape(auth_client):
    """Response contains all required top-level fields."""
    r = await auth_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "database" in body
    assert "suwayomi" in body
    assert "workers" in body
    assert body["status"] in ("healthy", "degraded", "unhealthy")
    assert "download_listener" in body["workers"]
    assert "scheduler" in body["workers"]
    assert "running" in body["workers"]["download_listener"]
    assert "running" in body["workers"]["scheduler"]
    assert "jobs" in body["workers"]["scheduler"]


# ---------------------------------------------------------------------------
# Database status
# ---------------------------------------------------------------------------


async def test_health_db_ok(auth_client):
    """When DB is reachable, database field is 'ok'."""
    r = await auth_client.get("/api/health")
    body = r.json()
    assert body["database"] == "ok"


# ---------------------------------------------------------------------------
# Suwayomi status
# ---------------------------------------------------------------------------


async def test_health_suwayomi_unreachable_when_not_configured(auth_client, monkeypatch):
    """When SUWAYOMI_URL is None, suwayomi status is 'unreachable'."""
    from app.config import settings
    monkeypatch.setattr(settings, "SUWAYOMI_URL", None)

    r = await auth_client.get("/api/health")
    body = r.json()
    assert body["suwayomi"]["status"] == "unreachable"
    assert body["status"] in ("degraded", "unhealthy")


async def test_health_suwayomi_unreachable_sets_degraded(auth_client, monkeypatch):
    """When Suwayomi ping fails (DB ok), overall status is degraded."""
    from app.config import settings
    from app.services import suwayomi
    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")

    async def _failing_ping(url, username, password):
        return False

    monkeypatch.setattr(suwayomi, "ping", _failing_ping)

    r = await auth_client.get("/api/health")
    body = r.json()
    assert body["suwayomi"]["status"] == "unreachable"
    assert body["status"] == "degraded"


async def test_health_suwayomi_ok_populates_sources(auth_client, monkeypatch):
    """When Suwayomi is reachable, sources list is populated from DB."""
    from datetime import datetime, timezone
    from app import database
    from app.config import settings
    from app.models.source import Source
    from app.services import suwayomi

    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")

    async def _ok_ping(url, username, password):
        return True

    async def _list_sources():
        return [{"id": "src-1", "display_name": "Test Source", "name": "Test Source"}]

    monkeypatch.setattr(suwayomi, "ping", _ok_ping)
    monkeypatch.setattr(suwayomi, "list_sources", _list_sources)

    async with database.AsyncSessionLocal() as db:
        db.add(Source(
            suwayomi_source_id="src-1", name="Test Source",
            priority=1, enabled=True, created_at=datetime.now(timezone.utc)
        ))
        await db.commit()

    r = await auth_client.get("/api/health")
    body = r.json()
    assert body["suwayomi"]["status"] == "ok"
    assert len(body["suwayomi"]["sources"]) == 1
    assert body["suwayomi"]["sources"][0]["name"] == "Test Source"
    assert body["suwayomi"]["sources"][0]["reachable"] is True


# ---------------------------------------------------------------------------
# Worker status
# ---------------------------------------------------------------------------


async def test_health_workers_down_when_not_started(auth_client, monkeypatch):
    """Workers report running=False before they have started."""
    monkeypatch.setattr(download_listener, "_started_at", None)
    monkeypatch.setattr(scheduler_module, "_started_at", None)

    r = await auth_client.get("/api/health")
    body = r.json()
    assert body["workers"]["download_listener"]["running"] is False
    assert body["workers"]["download_listener"]["uptime_seconds"] is None
    assert body["workers"]["scheduler"]["running"] is False


async def test_health_workers_running_reports_uptime(auth_client, monkeypatch):
    """Workers report running=True and uptime_seconds when started_at is set."""
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(download_listener, "_started_at", now)
    monkeypatch.setattr(scheduler_module, "_started_at", now)

    r = await auth_client.get("/api/health")
    body = r.json()
    assert body["workers"]["download_listener"]["running"] is True
    assert body["workers"]["download_listener"]["uptime_seconds"] is not None
    assert body["workers"]["download_listener"]["uptime_seconds"] >= 0


async def test_health_worker_down_sets_degraded(auth_client, monkeypatch):
    """If a worker is not running but DB is ok, overall status is degraded."""
    from app.config import settings
    from app.services import suwayomi

    monkeypatch.setattr(download_listener, "_started_at", None)
    monkeypatch.setattr(scheduler_module, "_started_at", None)
    monkeypatch.setattr(settings, "SUWAYOMI_URL", None)

    r = await auth_client.get("/api/health")
    body = r.json()
    assert body["status"] == "degraded"


# ---------------------------------------------------------------------------
# Overall status
# ---------------------------------------------------------------------------


async def test_health_all_ok_reports_healthy(auth_client, monkeypatch):
    """All components ok → status is healthy."""
    from app.config import settings
    from app.services import suwayomi

    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")

    async def _ok_ping(url, username, password):
        return True

    async def _list_sources():
        return []

    monkeypatch.setattr(suwayomi, "ping", _ok_ping)
    monkeypatch.setattr(suwayomi, "list_sources", _list_sources)

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(download_listener, "_started_at", now)
    monkeypatch.setattr(scheduler_module, "_started_at", now)

    # scheduler.running is a read-only property — patch get_status directly
    async def _mock_sched_status(db):
        return {"running": True, "uptime_seconds": 1.0, "jobs": []}

    monkeypatch.setattr(scheduler_module, "get_status", _mock_sched_status)

    r = await auth_client.get("/api/health")
    body = r.json()
    assert body["status"] == "healthy"
    assert body["database"] == "ok"
    assert body["suwayomi"]["status"] == "ok"
