"""Tests for source_selector and the suwayomi fetch_chapters / search_source functions.

Unit tests (no Suwayomi required):
    - effective_priority returns source.priority

Integration tests (require a live Suwayomi instance — skipped automatically if
SUWAYOMI_URL is not configured in .env.test):
    - search_source returns results with expected shape
    - fetch_chapters returns chapters with expected shape
    - chapter_number values are floats
    - build_chapter_source_map returns a non-empty dict with correct structure
    - find_upgrade_candidates returns correct pairs
"""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from app.models.comic import Comic, ComicStatus
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

    result = await source_selector.build_chapter_source_map(comic, db_session)

    assert isinstance(result, dict)
    assert len(result) > 0
    for ch_num, (src, manga_id) in result.items():
        assert isinstance(ch_num, float)
        assert isinstance(src, Source)
        assert isinstance(manga_id, str)


async def test_find_upgrade_candidates_no_upgrades_when_single_source(
    db_session, suwayomi_settings, test_manga_title
):
    source_id = await _first_searchable_source_id(test_manga_title)
    source = await _make_source(
        db_session, name="Live Source", priority=1, suwayomi_source_id=source_id
    )
    comic = await _make_comic(db_session, title=await _first_manga_title(source_id, test_manga_title))

    chapter_map = await source_selector.build_chapter_source_map(comic, db_session)
    if not chapter_map:
        pytest.skip("No chapters returned from live Suwayomi instance")

    ch_num, (_, manga_id) = next(iter(chapter_map.items()))
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
