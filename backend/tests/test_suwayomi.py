"""Tests for services/suwayomi.py.

Unit tests (no Suwayomi required):
    - ping() returns False when server responds with HTTP 401
    - ping() returns True when server responds with HTTP 200
    - ping() returns False when connection fails

Integration tests (require a live Suwayomi instance — skipped unless
SUWAYOMI_URL is set in .env.test):
    - ping() returns True for a reachable instance
    - list_sources(), search_source(), fetch_chapters(), enqueue_downloads()
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import suwayomi


# ---------------------------------------------------------------------------
# Unit tests — ping()
# ---------------------------------------------------------------------------


async def test_ping_returns_false_on_401():
    """ping() must return False when Suwayomi responds with HTTP 401."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.suwayomi.httpx.AsyncClient", return_value=mock_client):
        result = await suwayomi.ping("http://suwayomi", "user", "wrong-password")

    assert result is False


async def test_ping_returns_true_on_200():
    """ping() must return True when Suwayomi responds with HTTP 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.suwayomi.httpx.AsyncClient", return_value=mock_client):
        result = await suwayomi.ping("http://suwayomi", "user", "correct-password")

    assert result is True


async def test_ping_returns_false_on_connection_error():
    """ping() must return False when the server is unreachable."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("app.services.suwayomi.httpx.AsyncClient", return_value=mock_client):
        result = await suwayomi.ping("http://unreachable", "user", "pass")

    assert result is False


# ---------------------------------------------------------------------------
# Unit tests — poll_downloads()
# ---------------------------------------------------------------------------


async def test_poll_downloads_returns_all_queue_items():
    """poll_downloads() returns all queue items regardless of state."""
    mock_result = {
        "downloadStatus": {
            "queue": [
                {
                    "state": "FINISHED",
                    "chapter": {"id": 1, "name": "Chapter 1"},
                    "manga": {"title": "Test Manga", "source": {"displayName": "Source A"}},
                },
                {
                    "state": "ERROR",
                    "chapter": {"id": 2, "name": "Chapter 2"},
                    "manga": {"title": "Test Manga", "source": {"displayName": "Source A"}},
                },
                {
                    "state": "DOWNLOADING",
                    "chapter": {"id": 3, "name": "Chapter 3"},
                    "manga": {"title": "Test Manga", "source": {"displayName": "Source A"}},
                },
                {
                    "state": "QUEUED",
                    "chapter": {"id": 4, "name": "Chapter 4"},
                    "manga": {"title": "Test Manga", "source": {"displayName": "Source A"}},
                },
            ]
        }
    }

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.suwayomi._make_client", return_value=mock_client):
        results = await suwayomi.poll_downloads()

    assert len(results) == 4
    states = {r["state"] for r in results}
    assert states == {"FINISHED", "ERROR", "DOWNLOADING", "QUEUED"}


async def test_poll_downloads_returns_empty_when_queue_empty():
    """poll_downloads() returns an empty list when the download queue is empty."""
    mock_result = {"downloadStatus": {"queue": []}}

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.suwayomi._make_client", return_value=mock_client):
        results = await suwayomi.poll_downloads()

    assert results == []


async def test_poll_downloads_maps_fields_correctly():
    """poll_downloads() maps state, chapter id, name, manga title and source name correctly."""
    mock_result = {
        "downloadStatus": {
            "queue": [
                {
                    "state": "DOWNLOADING",
                    "chapter": {"id": 42, "name": "Episode 7"},
                    "manga": {"title": "My Manga", "source": {"displayName": "Webtoons EN"}},
                },
            ]
        }
    }

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.suwayomi._make_client", return_value=mock_client):
        results = await suwayomi.poll_downloads()

    assert len(results) == 1
    item = results[0]
    assert item["state"] == "DOWNLOADING"
    assert item["chapter_id"] == "42"
    assert item["chapter_name"] == "Episode 7"
    assert item["manga_title"] == "My Manga"
    assert item["source_name"] == "Webtoons EN"


# ---------------------------------------------------------------------------
# Integration tests — require live Suwayomi
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ping(suwayomi_settings):
    """ping() returns True for a reachable instance."""
    from app.config import settings

    result = await suwayomi.ping(
        settings.SUWAYOMI_URL,
        settings.SUWAYOMI_USERNAME,
        settings.SUWAYOMI_PASSWORD,
    )
    assert result is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_sources_returns_sources(suwayomi_settings):
    """list_sources() returns at least one source with expected fields."""
    sources = await suwayomi.list_sources()
    assert len(sources) > 0
    first = sources[0]
    assert "id" in first
    assert "name" in first
    assert "lang" in first
    assert "icon_url" in first


def _first_online_source(sources: list[dict]) -> dict:
    """Return the first non-local source. Local source has id '0'."""
    online = [s for s in sources if s["id"] != "0"]
    assert len(online) > 0, "No online sources installed on this Suwayomi instance"
    return online[0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_source_returns_results(suwayomi_settings, test_manga_title):
    """search_source() returns manga results with expected fields.

    Uses the first online source from list_sources() and searches for
    TEST_MANGA_TITLE. Requires at least one non-local source to be installed.
    """
    sources = await suwayomi.list_sources()
    source = _first_online_source(sources)
    source_id = source["id"]

    results = await suwayomi.search_source(source_id, test_manga_title)
    assert isinstance(results, list)
    assert len(results) > 0, (
        f"search_source returned no results for '{test_manga_title}' on source '{source['name']}' (id={source_id})"
    )
    first = results[0]
    assert "manga_id" in first
    assert "title" in first


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_chapters_returns_chapters(suwayomi_settings, test_manga_title):
    """fetch_chapters() returns chapters with expected fields.

    Searches for test_manga_title on the first available online source, takes the
    first manga result, and fetches its chapters.
    """
    sources = await suwayomi.list_sources()
    source_id = _first_online_source(sources)["id"]

    results = await suwayomi.search_source(source_id, test_manga_title)
    assert len(results) > 0, f"No search results for '{test_manga_title}'"

    manga_id = results[0]["manga_id"]
    chapters = await suwayomi.fetch_chapters(manga_id)

    assert isinstance(chapters, list)
    assert len(chapters) > 0, f"No chapters returned for manga_id={manga_id}"

    first = chapters[0]
    assert "chapter_number" in first
    assert "suwayomi_chapter_id" in first
    assert "chapter_published_at" in first
    assert isinstance(first["chapter_number"], float)
    assert isinstance(first["suwayomi_chapter_id"], str)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_enqueue_downloads_does_not_raise(suwayomi_settings, test_manga_title):
    """enqueue_downloads() accepts a valid chapter ID without raising.

    NOTE: this triggers a real download on the Suwayomi instance.
    Verify the chapter appears in Suwayomi's download queue UI after running.
    """
    sources = await suwayomi.list_sources()
    source_id = _first_online_source(sources)["id"]

    results = await suwayomi.search_source(source_id, test_manga_title)
    assert len(results) > 0, f"No search results for '{test_manga_title}'"

    manga_id = results[0]["manga_id"]
    chapters = await suwayomi.fetch_chapters(manga_id)
    assert len(chapters) > 0, f"No chapters for manga_id={manga_id}"

    chapter_id = chapters[0]["suwayomi_chapter_id"]
    await suwayomi.enqueue_downloads([chapter_id])  # raises on failure
