"""Integration tests for services/suwayomi.py against a live Suwayomi instance.

All tests are marked `integration` and skipped unless SUWAYOMI_URL is set in
.env.test. They verify that the service functions return well-formed responses —
scheduler and other callers rely on this contract.
"""
import pytest

from app.services import suwayomi

pytestmark = pytest.mark.integration


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
