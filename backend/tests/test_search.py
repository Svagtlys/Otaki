"""Tests for GET /api/search (issue #9) and thumbnail proxy.

Unit-style tests mock suwayomi.search_source and seed sources directly in the DB.
Integration tests require a configured Suwayomi instance via suwayomi_settings.
"""

import json

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
    body = r.json()
    assert body["results"] == []
    assert body["source_errors"] == []


async def test_search_skips_failed_source(logged_in_client, monkeypatch):
    """A source that throws populates source_errors and returns empty results for that source."""
    from app.services import suwayomi
    await _add_source()

    async def _failing_search(source_id, query):
        raise Exception("source unavailable")

    monkeypatch.setattr(suwayomi, "search_source", _failing_search)

    r = await logged_in_client.get("/api/search?q=test")
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == []
    assert len(body["source_errors"]) == 1
    assert body["source_errors"][0]["source_name"] == "Test Source"
    assert body["source_errors"][0]["reason"] == "unexpected error"


async def test_search_timeout_populates_source_error(logged_in_client, monkeypatch):
    """A TimeoutException from a source maps to 'connection timed out' in source_errors."""
    import httpx
    from app.services import suwayomi
    await _add_source()

    async def _timeout_search(source_id, query):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(suwayomi, "search_source", _timeout_search)

    r = await logged_in_client.get("/api/search?q=test")
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == []
    assert body["source_errors"][0]["reason"] == "connection timed out"


async def test_search_result_shape(logged_in_client, monkeypatch):
    from app.services import suwayomi
    await _add_source()

    async def _mock_search(source_id, query):
        return [{"manga_id": "1", "title": "Test Manga", "cover_url": None, "synopsis": None, "url": "http://example.com"}]

    monkeypatch.setattr(suwayomi, "search_source", _mock_search)

    r = await logged_in_client.get("/api/search?q=test")
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["title"] == "Test Manga"
    assert "source_id" in result
    assert "source_name" in result
    assert result["source_name"] == "Test Source"
    assert result["suwayomi_manga_id"] == "1"
    assert body["source_errors"] == []


async def test_search_cover_urls(logged_in_client, monkeypatch):
    """cover_url is absolute Suwayomi URL; cover_display_url is the proxied URL."""
    from app.services import suwayomi
    from app.config import settings
    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")
    await _add_source()

    async def _mock_search(source_id, query):
        return [{"manga_id": "1", "title": "Test Manga",
                 "cover_url": "/api/v1/manga/1/thumbnail",
                 "synopsis": None, "url": None}]

    monkeypatch.setattr(suwayomi, "search_source", _mock_search)

    r = await logged_in_client.get("/api/search?q=test")
    assert r.status_code == 200
    result = r.json()["results"][0]
    assert result["cover_url"] == "https://suwayomi.example.com/api/v1/manga/1/thumbnail"
    assert result["cover_display_url"].startswith("/api/search/thumbnail?url=")


async def test_thumbnail_proxy_no_auth_required(auth_client, monkeypatch):
    """Thumbnail proxy must be accessible without JWT (img tags can't send auth headers)."""
    from app.config import settings
    import httpx

    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")

    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            class R:
                status_code = 200
                content = b"img"
                headers = {"content-type": "image/jpeg"}
            return R()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    r = await auth_client.get("/api/search/thumbnail?url=https://suwayomi.example.com/img.jpg")
    assert r.status_code == 200


async def test_thumbnail_proxy_rejects_non_suwayomi_url(logged_in_client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")
    r = await logged_in_client.get("/api/search/thumbnail?url=https://evil.com/img.jpg")
    assert r.status_code == 400


async def test_thumbnail_proxy_fetches_from_suwayomi(logged_in_client, monkeypatch):
    from app.config import settings
    import httpx

    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")

    class FakeResponse:
        status_code = 200
        content = b"fake-thumbnail"
        headers = {"content-type": "image/jpeg"}

    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    import urllib.parse
    url = urllib.parse.quote("https://suwayomi.example.com/api/v1/manga/1/thumbnail", safe="")
    r = await logged_in_client.get(f"/api/search/thumbnail?url={url}")
    assert r.status_code == 200
    assert r.content == b"fake-thumbnail"


async def test_thumbnail_proxy_timeout_returns_504(logged_in_client, monkeypatch):
    """A timeout from Suwayomi returns 504, not 500."""
    from app.config import settings
    import httpx

    monkeypatch.setattr(settings, "SUWAYOMI_URL", "https://suwayomi.example.com")

    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    import urllib.parse
    url = urllib.parse.quote("https://suwayomi.example.com/img.jpg", safe="")
    r = await logged_in_client.get(f"/api/search/thumbnail?url={url}")
    assert r.status_code == 504


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
    assert len(r.json()["results"]) == 2
    assert set(called_with) == {"src-1", "src-2"}


# ---------------------------------------------------------------------------
# Integration tests — require live Suwayomi
# ---------------------------------------------------------------------------


async def test_search_live_returns_list(suwayomi_credentials, suwayomi_settings, logged_in_client, monkeypatch, test_manga_title):
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
    body = r.json()
    assert "results" in body
    assert "source_errors" in body
    assert isinstance(body["results"], list)


async def test_search_live_result_has_required_fields(suwayomi_credentials, suwayomi_settings, logged_in_client, monkeypatch, test_manga_title):
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
        try:
            results = await _search_source(s["id"], test_manga_title)
        except Exception:
            continue
        if results:
            chosen = s
            break
    if not chosen:
        pytest.skip(f"No source returned results for {test_manga_title!r}")

    await _add_source(name=chosen["name"], suwayomi_source_id=chosen["id"])

    r = await logged_in_client.get(f"/api/search?q={test_manga_title}")
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) > 0
    for result in results:
        assert "title" in result
        assert "source_id" in result
        assert "source_name" in result
        assert "cover_url" in result
        assert "synopsis" in result
        assert "url" in result


# ---------------------------------------------------------------------------
# GET /api/search/stream tests (issue #91)
# ---------------------------------------------------------------------------


def _parse_stream(text: str) -> list:
    """Parse SSE response text into a list of parsed data payloads."""
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            raw = line[6:].strip()
            if raw == "[DONE]":
                events.append("[DONE]")
            else:
                events.append(json.loads(raw))
    return events


async def test_search_stream_requires_auth(auth_client):
    r = await auth_client.get("/api/search/stream?q=test")
    assert r.status_code == 401


async def test_search_stream_rejects_empty_query(logged_in_client):
    r = await logged_in_client.get("/api/search/stream?q=")
    assert r.status_code == 422


async def test_search_stream_emits_per_source_events(logged_in_client, monkeypatch):
    """Two sources both succeed — two result events arrive, then [DONE]."""
    from app.services import suwayomi
    await _add_source(name="Source A", suwayomi_source_id="src-a", priority=1)
    await _add_source(name="Source B", suwayomi_source_id="src-b", priority=2)

    async def _mock_search(source_id, query):
        return [{"manga_id": f"{source_id}-1", "title": f"Manga from {source_id}",
                 "cover_url": None, "synopsis": None, "url": None}]

    monkeypatch.setattr(suwayomi, "search_source", _mock_search)

    r = await logged_in_client.get("/api/search/stream?q=test")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")

    events = _parse_stream(r.text)
    result_events = [e for e in events if e != "[DONE]"]
    assert len(result_events) == 2
    source_names = {e["source_name"] for e in result_events}
    assert source_names == {"Source A", "Source B"}
    for e in result_events:
        assert "results" in e
        assert len(e["results"]) == 1
        assert e["results"][0]["title"].startswith("Manga from")
    assert events[-1] == "[DONE]"


async def test_search_stream_emits_error_for_failed_source(logged_in_client, monkeypatch):
    """One source raises, other succeeds — error event for the bad source, result event for the good one, then [DONE]."""
    from app.services import suwayomi
    await _add_source(name="Good Source", suwayomi_source_id="src-good", priority=1)
    await _add_source(name="Bad Source", suwayomi_source_id="src-bad", priority=2)

    async def _mock_search(source_id, query):
        if source_id == "src-bad":
            raise Exception("source down")
        return [{"manga_id": "1", "title": "Good Manga", "cover_url": None, "synopsis": None, "url": None}]

    monkeypatch.setattr(suwayomi, "search_source", _mock_search)

    r = await logged_in_client.get("/api/search/stream?q=test")
    assert r.status_code == 200

    events = _parse_stream(r.text)
    assert events[-1] == "[DONE]"
    data_events = [e for e in events if e != "[DONE]"]
    assert len(data_events) == 2

    error_events = [e for e in data_events if "error" in e]
    result_events = [e for e in data_events if "results" in e]
    assert len(error_events) == 1
    assert len(result_events) == 1
    assert error_events[0]["source_name"] == "Bad Source"
    assert result_events[0]["source_name"] == "Good Source"
