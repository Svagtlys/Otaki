"""Tests for GET /api/search (issue #9).

Unit-style tests mock suwayomi.search_source and seed sources directly in the DB.
Integration tests require a configured Suwayomi instance via suwayomi_settings.
"""

import pytest
from datetime import datetime, timezone

from app.models.source import Source


async def _add_source(*, name="Test Source", suwayomi_source_id="src-1", priority=1):
    """Seed a source row directly via the DB session used by the app."""
    from app import database
    async with database.AsyncSessionLocal() as db:
        source = Source(
            suwayomi_source_id=suwayomi_source_id,
            name=name,
            priority=priority,
            enabled=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        return source


# ---------------------------------------------------------------------------
# Unit-style tests — no live Suwayomi
# ---------------------------------------------------------------------------


async def test_search_requires_auth(auth_client):
    r = await auth_client.get("/api/search?q=test")
    assert r.status_code == 401


async def test_search_missing_query(logged_in_client):
    r = await logged_in_client.get("/api/search")
    assert r.status_code == 422


async def test_search_returns_empty_when_no_sources(logged_in_client):
    r = await logged_in_client.get("/api/search?q=anything")
    assert r.status_code == 200
    assert r.json() == []


async def test_search_skips_failed_source(logged_in_client, monkeypatch):
    from app.services import suwayomi
    await _add_source()

    async def _failing_search(source_id, query):
        raise Exception("source unavailable")

    monkeypatch.setattr(suwayomi, "search_source", _failing_search)

    r = await logged_in_client.get("/api/search?q=test")
    assert r.status_code == 200
    assert r.json() == []


async def test_search_result_shape(logged_in_client, monkeypatch):
    from app.services import suwayomi
    await _add_source()

    async def _mock_search(source_id, query):
        return [{"manga_id": "1", "title": "Test Manga", "cover_url": None, "synopsis": None, "url": "http://example.com"}]

    monkeypatch.setattr(suwayomi, "search_source", _mock_search)

    r = await logged_in_client.get("/api/search?q=test")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    result = results[0]
    assert result["title"] == "Test Manga"
    assert "source_id" in result
    assert "source_name" in result
    assert result["source_name"] == "Test Source"


async def test_search_fans_out_to_all_sources(logged_in_client, monkeypatch):
    from app.services import suwayomi
    await _add_source(name="Source A", suwayomi_source_id="src-1", priority=1)
    await _add_source(name="Source B", suwayomi_source_id="src-2", priority=2)

    called_with = []

    async def _mock_search(source_id, query):
        called_with.append(source_id)
        return [{"manga_id": source_id, "title": f"Result from {source_id}", "cover_url": None, "synopsis": None, "url": None}]

    monkeypatch.setattr(suwayomi, "search_source", _mock_search)

    r = await logged_in_client.get("/api/search?q=test")
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert set(called_with) == {"src-1", "src-2"}


# ---------------------------------------------------------------------------
# Integration tests — require live Suwayomi
# ---------------------------------------------------------------------------


async def test_search_live_returns_list(suwayomi_credentials, logged_in_client, monkeypatch, test_manga_title):
    from app.config import settings
    from app.services.suwayomi import list_sources as _list_sources
    monkeypatch.setattr(settings, "SUWAYOMI_URL", suwayomi_credentials["url"])
    monkeypatch.setattr(settings, "SUWAYOMI_USERNAME", suwayomi_credentials["username"])
    monkeypatch.setattr(settings, "SUWAYOMI_PASSWORD", suwayomi_credentials["password"])

    sources = await _list_sources()
    if not sources:
        pytest.skip("No sources on live Suwayomi instance")

    await _add_source(name=sources[0]["name"], suwayomi_source_id=sources[0]["id"])

    r = await logged_in_client.get(f"/api/search?q={test_manga_title}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_search_live_result_has_required_fields(suwayomi_credentials, logged_in_client, monkeypatch, test_manga_title):
    from app.config import settings
    from app.services.suwayomi import list_sources as _list_sources, search_source as _search_source
    monkeypatch.setattr(settings, "SUWAYOMI_URL", suwayomi_credentials["url"])
    monkeypatch.setattr(settings, "SUWAYOMI_USERNAME", suwayomi_credentials["username"])
    monkeypatch.setattr(settings, "SUWAYOMI_PASSWORD", suwayomi_credentials["password"])

    sources = await _list_sources()
    if not sources:
        pytest.skip("No sources on live Suwayomi instance")

    chosen = None
    for s in sources:
        results = await _search_source(s["id"], test_manga_title)
        if results:
            chosen = s
            break
    if not chosen:
        pytest.skip(f"No source returned results for {test_manga_title!r}")

    await _add_source(name=chosen["name"], suwayomi_source_id=chosen["id"])

    r = await logged_in_client.get(f"/api/search?q={test_manga_title}")
    assert r.status_code == 200
    results = r.json()
    assert len(results) > 0
    for result in results:
        assert "title" in result
        assert "source_id" in result
        assert "source_name" in result
        assert "cover_url" in result
        assert "synopsis" in result
        assert "url" in result
