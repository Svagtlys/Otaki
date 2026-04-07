"""Tests for source_selector and the suwayomi fetch_chapters / search_source functions.

Unit tests (no Suwayomi required):
    - effective_priority returns source.priority
    - build_chapter_source_map uses second result when first title does not match comic
    - build_chapter_source_map returns ({}, []) when no result title matches comic
    - build_chapter_source_map returns source_errors when a source raises

Integration tests (require a live Suwayomi instance — skipped automatically if
SUWAYOMI_URL is not configured in .env.test):
    - search_source returns results with expected shape
    - fetch_chapters returns chapters with expected shape
    - chapter_number values are floats
    - build_chapter_source_map returns a non-empty dict with correct structure
    - find_upgrade_candidates returns correct pairs
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from app.models.comic import Comic, ComicStatus
from app.models.comic_alias import ComicAlias
from app.models.comic_source_pin import ComicSourcePin
from app.models.source import Source
from app.services import source_selector, suwayomi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_source(db, *, name: str, priority: int, suwayomi_source_id: str = None) -> Source:
    source = Source(
        suwayomi_source_id=suwayomi_source_id or f"src-{priority}",
        name=name,
        priority=priority,
        enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def _make_comic(db, *, title: str = "Test Comic") -> Comic:
    comic = Comic(
        title=title,
        library_title=title,
        status=ComicStatus.tracking,
        created_at=datetime.now(timezone.utc),
    )
    db.add(comic)
    await db.commit()
    await db.refresh(comic)
    return comic


async def _make_assignment(
    db,
    *,
    comic: Comic,
    source: Source,
    chapter_number: float,
    is_active: bool = True,
) -> ChapterAssignment:
    assignment = ChapterAssignment(
        comic_id=comic.id,
        chapter_number=chapter_number,
        source_id=source.id,
        suwayomi_manga_id="1",
        suwayomi_chapter_id="1",
        download_status=DownloadStatus.done,
        is_active=is_active,
        chapter_published_at=datetime.now(timezone.utc),
        relocation_status=RelocationStatus.done,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


# ---------------------------------------------------------------------------
# Unit tests — no Suwayomi required
# ---------------------------------------------------------------------------


async def test_effective_priority_returns_source_priority(db_session):
    source = await _make_source(db_session, name="Source A", priority=3)
    comic = await _make_comic(db_session)
    result = await source_selector.effective_priority(source, comic, db_session)
    assert result == 3


# ---------------------------------------------------------------------------
# Unit tests — _find_matching_result / title-match guard
# ---------------------------------------------------------------------------


async def test_build_chapter_source_map_uses_second_result_when_first_title_does_not_match(
    db_session,
):
    """If the first search result title does not match comic.title, the helper
    must skip it and use the matching result further down the list."""
    source = await _make_source(db_session, name="Source A", priority=1)
    comic = await _make_comic(db_session, title="Correct Title")

    fake_results = [
        {"manga_id": "wrong-id", "title": "Completely Different Manga"},
        {"manga_id": "correct-id", "title": "Correct Title"},
    ]
    fake_chapters = [
        {
            "chapter_number": 1.0,
            "suwayomi_chapter_id": "ch-1",
            "chapter_published_at": datetime.now(timezone.utc),
            "volume_number": None,
            "source_chapter_name": "Chapter 1",
        }
    ]

    with (
        patch(
            "app.services.source_selector.suwayomi.search_source",
            new=AsyncMock(return_value=fake_results),
        ),
        patch(
            "app.services.source_selector.suwayomi.fetch_chapters",
            new=AsyncMock(return_value=fake_chapters),
        ),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert len(chapter_map) == 1
    _src, manga_id, _ch = chapter_map[1.0]
    assert manga_id == "correct-id"
    assert source_errors == []


async def test_build_chapter_source_map_returns_empty_when_no_title_match(db_session):
    """If no search result matches comic.title, the source must be skipped and
    build_chapter_source_map must return an empty chapter map with no error."""
    source = await _make_source(db_session, name="Source A", priority=1)
    comic = await _make_comic(db_session, title="Missing Title")

    fake_results = [
        {"manga_id": "some-id", "title": "Something Else Entirely"},
    ]

    with patch(
        "app.services.source_selector.suwayomi.search_source",
        new=AsyncMock(return_value=fake_results),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert chapter_map == {}
    assert source_errors == []


async def test_build_chapter_source_map_returns_error_when_source_raises(db_session):
    """A source that raises populates source_errors; chapter_map is still returned
    for any sources that succeeded."""
    import httpx
    await _make_source(db_session, name="Failing Source", priority=1)
    comic = await _make_comic(db_session, title="Any Title")

    with patch(
        "app.services.source_selector.suwayomi.search_source",
        new=AsyncMock(side_effect=httpx.TimeoutException("timed out")),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert chapter_map == {}
    assert len(source_errors) == 1
    assert source_errors[0]["source_name"] == "Failing Source"
    assert source_errors[0]["reason"] == "connection timed out"


async def test_build_chapter_source_map_matches_alias_title_in_results(db_session):
    """If comic.title doesn't match any result, but an alias title does, that result is used."""
    source = await _make_source(db_session, name="Source A", priority=1)
    comic = await _make_comic(db_session, title="Primary Title")

    # Add an alias whose title matches the search result
    alias = ComicAlias(comic_id=comic.id, title="Alias Title")
    db_session.add(alias)
    await db_session.commit()

    fake_results = [
        {"manga_id": "alias-match-id", "title": "Alias Title"},
    ]
    fake_chapters = [
        {
            "chapter_number": 1.0,
            "suwayomi_chapter_id": "ch-1",
            "chapter_published_at": datetime.now(timezone.utc),
            "volume_number": None,
            "source_chapter_name": "Chapter 1",
        }
    ]

    with (
        patch(
            "app.services.source_selector.suwayomi.search_source",
            new=AsyncMock(return_value=fake_results),
        ),
        patch(
            "app.services.source_selector.suwayomi.fetch_chapters",
            new=AsyncMock(return_value=fake_chapters),
        ),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert len(chapter_map) == 1
    _src, manga_id, _ch = chapter_map[1.0]
    assert manga_id == "alias-match-id"
    assert source_errors == []


async def test_build_chapter_source_map_retries_search_with_alias_title(db_session):
    """If primary title search returns no results, alias titles are tried as search queries."""
    source = await _make_source(db_session, name="Source A", priority=1)
    comic = await _make_comic(db_session, title="Primary Title")

    alias = ComicAlias(comic_id=comic.id, title="Alias Title")
    db_session.add(alias)
    await db_session.commit()

    fake_chapters = [
        {
            "chapter_number": 1.0,
            "suwayomi_chapter_id": "ch-1",
            "chapter_published_at": datetime.now(timezone.utc),
            "volume_number": None,
            "source_chapter_name": "Chapter 1",
        }
    ]

    call_count = 0

    async def _search_side_effect(source_id, query):
        nonlocal call_count
        call_count += 1
        if query == "Primary Title":
            return []  # no results on primary
        if query == "Alias Title":
            return [{"manga_id": "alias-search-id", "title": "Alias Title"}]
        return []

    with (
        patch(
            "app.services.source_selector.suwayomi.search_source",
            new=AsyncMock(side_effect=_search_side_effect),
        ),
        patch(
            "app.services.source_selector.suwayomi.fetch_chapters",
            new=AsyncMock(return_value=fake_chapters),
        ),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert len(chapter_map) == 1
    _src, manga_id, _ch = chapter_map[1.0]
    assert manga_id == "alias-search-id"
    assert call_count == 2  # once for primary, once for alias
    assert source_errors == []


async def test_build_chapter_source_map_error_does_not_block_other_sources(db_session):
    """If one source fails, successful sources still contribute to the chapter map."""
    await _make_source(db_session, name="Good Source", priority=1, suwayomi_source_id="src-good")
    await _make_source(db_session, name="Bad Source", priority=2, suwayomi_source_id="src-bad")
    comic = await _make_comic(db_session, title="My Comic")

    fake_chapters = [
        {
            "chapter_number": 1.0,
            "suwayomi_chapter_id": "ch-1",
            "chapter_published_at": datetime.now(timezone.utc),
            "volume_number": None,
        }
    ]

    async def _selective_search(source_id, query):
        if source_id == "src-bad":
            raise ConnectionError("refused")
        return [{"manga_id": "m-1", "title": "My Comic"}]

    with (
        patch(
            "app.services.source_selector.suwayomi.search_source",
            new=AsyncMock(side_effect=_selective_search),
        ),
        patch(
            "app.services.source_selector.suwayomi.fetch_chapters",
            new=AsyncMock(return_value=fake_chapters),
        ),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert len(chapter_map) == 1
    assert len(source_errors) == 1
    assert source_errors[0]["source_name"] == "Bad Source"


# ---------------------------------------------------------------------------
# Unit tests — source pin behaviour
# ---------------------------------------------------------------------------


async def test_build_chapter_source_map_uses_pin_when_present(db_session):
    """When a ComicSourcePin exists for a source, fetch_chapters is called directly
    with the pinned suwayomi_manga_id and search_source is never called."""
    source = await _make_source(db_session, name="Pinned Source", priority=1)
    comic = await _make_comic(db_session, title="Pinned Comic")

    pin = ComicSourcePin(comic_id=comic.id, source_id=source.id, suwayomi_manga_id="pinned-id")
    db_session.add(pin)
    await db_session.commit()

    fake_chapters = [
        {
            "chapter_number": 1.0,
            "suwayomi_chapter_id": "ch-1",
            "chapter_published_at": datetime.now(timezone.utc),
            "volume_number": None,
            "source_chapter_name": "Chapter 1",
        }
    ]

    mock_fetch = AsyncMock(return_value=fake_chapters)

    with (
        patch(
            "app.services.source_selector.suwayomi.search_source",
            side_effect=AssertionError("search_source must not be called for a pinned source"),
        ),
        patch(
            "app.services.source_selector.suwayomi.fetch_chapters",
            new=mock_fetch,
        ),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    mock_fetch.assert_called_once_with("pinned-id")
    assert len(chapter_map) == 1
    assert source_errors == []


async def test_build_chapter_source_map_multiple_pins_same_source(db_session):
    """Multiple ComicSourcePin rows for the same source each trigger a separate
    fetch_chapters call; all returned chapters appear in the map."""
    source = await _make_source(db_session, name="Multi-Pin Source", priority=1)
    comic = await _make_comic(db_session, title="Multi-Pin Comic")

    pin_a = ComicSourcePin(comic_id=comic.id, source_id=source.id, suwayomi_manga_id="pin-a")
    pin_b = ComicSourcePin(comic_id=comic.id, source_id=source.id, suwayomi_manga_id="pin-b")
    db_session.add(pin_a)
    db_session.add(pin_b)
    await db_session.commit()

    chapters_a = [
        {
            "chapter_number": 1.0,
            "suwayomi_chapter_id": "ch-a-1",
            "chapter_published_at": datetime.now(timezone.utc),
            "volume_number": None,
            "source_chapter_name": "Chapter 1",
        }
    ]
    chapters_b = [
        {
            "chapter_number": 2.0,
            "suwayomi_chapter_id": "ch-b-1",
            "chapter_published_at": datetime.now(timezone.utc),
            "volume_number": None,
            "source_chapter_name": "Chapter 2",
        }
    ]

    mock_fetch = AsyncMock(side_effect=[chapters_a, chapters_b])

    with (
        patch(
            "app.services.source_selector.suwayomi.search_source",
            side_effect=AssertionError("search_source must not be called for pinned sources"),
        ),
        patch(
            "app.services.source_selector.suwayomi.fetch_chapters",
            new=mock_fetch,
        ),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert mock_fetch.call_count == 2
    assert 1.0 in chapter_map
    assert 2.0 in chapter_map
    assert source_errors == []


async def test_build_chapter_source_map_partial_pin_failure_does_not_block_other_ids(db_session):
    """If one pinned manga_id fails, the other pin's chapter still appears in the map
    and source_errors is empty (partial pin failure is not a source-level error)."""
    source = await _make_source(db_session, name="Partial Pin Source", priority=1)
    comic = await _make_comic(db_session, title="Partial Pin Comic")

    pin_ok = ComicSourcePin(comic_id=comic.id, source_id=source.id, suwayomi_manga_id="pin-ok")
    pin_fail = ComicSourcePin(comic_id=comic.id, source_id=source.id, suwayomi_manga_id="pin-fail")
    db_session.add(pin_ok)
    db_session.add(pin_fail)
    await db_session.commit()

    fake_chapter = {
        "chapter_number": 1.0,
        "suwayomi_chapter_id": "ch-1",
        "chapter_published_at": datetime.now(timezone.utc),
        "volume_number": None,
        "source_chapter_name": "Chapter 1",
    }

    async def _fetch_side_effect(manga_id):
        if manga_id == "pin-fail":
            raise httpx.TimeoutException("timed out")
        return [fake_chapter]

    with (
        patch(
            "app.services.source_selector.suwayomi.search_source",
            side_effect=AssertionError("search_source must not be called for pinned sources"),
        ),
        patch(
            "app.services.source_selector.suwayomi.fetch_chapters",
            new=AsyncMock(side_effect=_fetch_side_effect),
        ),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert len(chapter_map) == 1
    assert source_errors == []


async def test_build_chapter_source_map_pinned_source_skips_unpinned_search(db_session):
    """search_source is only called for sources that have no pin; pinned sources
    use fetch_chapters directly."""
    source_a = await _make_source(
        db_session, name="Source A (pinned)", priority=1, suwayomi_source_id="src-a"
    )
    source_b = await _make_source(
        db_session, name="Source B (unpinned)", priority=2, suwayomi_source_id="src-b"
    )
    comic = await _make_comic(db_session, title="Mixed Comic")

    pin = ComicSourcePin(comic_id=comic.id, source_id=source_a.id, suwayomi_manga_id="pin-a-id")
    db_session.add(pin)
    await db_session.commit()

    fake_chapters = [
        {
            "chapter_number": 1.0,
            "suwayomi_chapter_id": "ch-1",
            "chapter_published_at": datetime.now(timezone.utc),
            "volume_number": None,
            "source_chapter_name": "Chapter 1",
        }
    ]

    searched_source_ids = []

    async def _search_side_effect(source_id, query):
        searched_source_ids.append(source_id)
        if source_id == "src-b":
            return [{"manga_id": "manga-b", "title": "Mixed Comic"}]
        return []

    with (
        patch(
            "app.services.source_selector.suwayomi.search_source",
            new=AsyncMock(side_effect=_search_side_effect),
        ),
        patch(
            "app.services.source_selector.suwayomi.fetch_chapters",
            new=AsyncMock(return_value=fake_chapters),
        ),
    ):
        chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert "src-a" not in searched_source_ids
    assert "src-b" in searched_source_ids
    # Both sources should contribute chapters (pinned via fetch, unpinned via search+fetch)
    assert len(chapter_map) > 0


# ---------------------------------------------------------------------------
# Integration tests — require live Suwayomi
# ---------------------------------------------------------------------------


async def test_search_source_returns_list(suwayomi_settings, test_manga_title):
    results = await suwayomi.search_source(
        source_id=await _first_searchable_source_id(test_manga_title),
        query=test_manga_title,
    )
    assert isinstance(results, list)


async def test_search_source_result_shape(suwayomi_settings, test_manga_title):
    results = await suwayomi.search_source(
        source_id=await _first_searchable_source_id(test_manga_title),
        query=test_manga_title,
    )
    if not results:
        pytest.skip("No search results from live Suwayomi instance for this source")
    first = results[0]
    assert "manga_id" in first
    assert "title" in first
    assert isinstance(first["manga_id"], str)


async def test_fetch_chapters_returns_list(suwayomi_settings, test_manga_title):
    manga_id = await _first_manga_id(test_manga_title)
    chapters = await suwayomi.fetch_chapters(manga_id)
    assert isinstance(chapters, list)
    assert len(chapters) > 0


async def test_fetch_chapters_expected_keys(suwayomi_settings, test_manga_title):
    manga_id = await _first_manga_id(test_manga_title)
    chapters = await suwayomi.fetch_chapters(manga_id)
    ch = chapters[0]
    assert "chapter_number" in ch
    assert "suwayomi_chapter_id" in ch
    assert "chapter_published_at" in ch
    assert "volume_number" in ch


async def test_fetch_chapters_chapter_number_is_float(suwayomi_settings, test_manga_title):
    manga_id = await _first_manga_id(test_manga_title)
    chapters = await suwayomi.fetch_chapters(manga_id)
    for ch in chapters:
        assert isinstance(ch["chapter_number"], float)


async def test_fetch_chapters_published_at_is_datetime(suwayomi_settings, test_manga_title):
    manga_id = await _first_manga_id(test_manga_title)
    chapters = await suwayomi.fetch_chapters(manga_id)
    for ch in chapters:
        assert isinstance(ch["chapter_published_at"], datetime)


async def test_build_chapter_source_map_returns_dict(db_session, suwayomi_settings, test_manga_title):
    source_id = await _first_searchable_source_id(test_manga_title)
    source = await _make_source(
        db_session, name="Live Source", priority=1, suwayomi_source_id=source_id
    )
    comic = await _make_comic(db_session, title=await _first_manga_title(source_id, test_manga_title))

    chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert isinstance(chapter_map, dict)
    assert len(chapter_map) > 0
    for ch_num, (src, manga_id, ch_data) in chapter_map.items():
        assert isinstance(ch_num, float)
        assert isinstance(src, Source)
        assert isinstance(manga_id, str)
        assert "suwayomi_chapter_id" in ch_data
        assert "chapter_published_at" in ch_data
        assert "source_chapter_name" in ch_data
        assert "source_manga_title" in ch_data
    assert isinstance(source_errors, list)


async def test_find_upgrade_candidates_no_upgrades_when_single_source(
    db_session, suwayomi_settings, test_manga_title
):
    source_id = await _first_searchable_source_id(test_manga_title)
    source = await _make_source(
        db_session, name="Live Source", priority=1, suwayomi_source_id=source_id
    )
    comic = await _make_comic(db_session, title=await _first_manga_title(source_id, test_manga_title))

    chapter_map, _ = await source_selector.build_chapter_source_map(comic, db_session)
    if not chapter_map:
        pytest.skip("No chapters returned from live Suwayomi instance")

    ch_num, (_, manga_id, _ch_data) = next(iter(chapter_map.items()))
    await _make_assignment(
        db_session, comic=comic, source=source, chapter_number=ch_num
    )

    candidates = await source_selector.find_upgrade_candidates(comic, db_session)
    assert candidates == []


# ---------------------------------------------------------------------------
# Live Suwayomi helpers — fetch a real source ID and manga ID to use in tests
# ---------------------------------------------------------------------------


async def _first_searchable_source_id(query: str = "a") -> str:
    """Return the first source that returns results for the given query.
    Skips sources like 'Local source' (id: 0) that don't support search.
    """
    sources = await suwayomi.list_sources()
    if not sources:
        pytest.skip("No sources available on live Suwayomi instance")
    for source in sources:
        results = await suwayomi.search_source(source["id"], query)
        if results:
            return source["id"]
    pytest.skip(f"No source returned results for query {query!r}")


async def _first_source_id() -> str:
    return await _first_searchable_source_id()


async def _first_manga_title(source_id: str, query: str = "a") -> str:
    results = await suwayomi.search_source(source_id, query)
    if not results:
        pytest.skip("No search results from live Suwayomi instance")
    return results[0]["title"]


async def _first_manga_id(query: str = "a") -> str:
    source_id = await _first_searchable_source_id(query)
    results = await suwayomi.search_source(source_id, query)
    if not results:
        pytest.skip("No search results from live Suwayomi instance")
    return results[0]["manga_id"]


async def _webtoons_en_source_id() -> str:
    """Return the suwayomi_source_id for the Webtoons EN source, or skip."""
    sources = await suwayomi.list_sources()
    for source in sources:
        name = source.get("name", "")
        lang = source.get("lang", "")
        if "webtoon" in name.lower() and lang.lower() == "en":
            return source["id"]
    pytest.skip("Webtoons EN source not installed on live Suwayomi instance")


@pytest.mark.integration
async def test_build_chapter_source_map_webtoons_title_match(db_session, suwayomi_settings, test_manga_title):
    """Integration: build_chapter_source_map correctly matches a manga title on the
    Webtoons EN source and returns a non-empty chapter map.

    Uses TEST_MANGA_TITLE from .env.test. Skips if the title is not present in
    the live Suwayomi instance's search results.
    """
    comic_title = test_manga_title
    source_id = await _webtoons_en_source_id()

    # Verify the title actually exists on this Suwayomi instance before asserting
    search_results = await suwayomi.search_source(source_id, comic_title)
    matched = source_selector._find_matching_result(search_results, [comic_title])
    if matched is None:
        pytest.skip(
            f"TEST_MANGA_TITLE {comic_title!r} not found in Webtoons EN search results on this Suwayomi instance"
        )

    source = await _make_source(
        db_session,
        name="Webtoons EN",
        priority=1,
        suwayomi_source_id=source_id,
    )
    comic = await _make_comic(db_session, title=comic_title)

    chapter_map, source_errors = await source_selector.build_chapter_source_map(comic, db_session)

    assert isinstance(chapter_map, dict)
    assert len(chapter_map) > 0
    for ch_num, (src, manga_id, ch_data) in chapter_map.items():
        assert isinstance(ch_num, float)
        assert isinstance(src, Source)
        assert isinstance(manga_id, str)
        assert "suwayomi_chapter_id" in ch_data
        assert "chapter_published_at" in ch_data
        assert "source_chapter_name" in ch_data
        assert "source_manga_title" in ch_data
    assert isinstance(source_errors, list)
