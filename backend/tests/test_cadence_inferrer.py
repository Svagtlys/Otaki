"""Tests for cadence_inferrer.infer_cadence.

Unit tests (in-memory SQLite, no Suwayomi required):
    - Returns None with 0 active chapters
    - Returns None with exactly 1 active chapter
    - Returns correct median with evenly-spaced chapters
    - Hiatus gaps (> 3× initial median) are filtered out
    - Ignores inactive chapters when computing cadence
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from app.models.comic import Comic, ComicStatus
from app.models.source import Source
from app.services import cadence_inferrer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


async def _make_comic(db) -> Comic:
    comic = Comic(
        title="Test Comic",
        library_title="Test Comic",
        status=ComicStatus.tracking,
        created_at=_T0,
    )
    db.add(comic)
    await db.commit()
    await db.refresh(comic)
    return comic


async def _make_source(db) -> Source:
    source = Source(
        suwayomi_source_id="src-test",
        name="Test Source",
        priority=1,
        enabled=True,
        created_at=_T0,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def _add_chapter(
    db,
    comic: Comic,
    source: Source,
    *,
    chapter_number: float,
    published_at: datetime,
    is_active: bool = True,
) -> ChapterAssignment:
    a = ChapterAssignment(
        comic_id=comic.id,
        chapter_number=chapter_number,
        volume_number=None,
        source_id=source.id,
        suwayomi_manga_id="manga-1",
        suwayomi_chapter_id=f"ch-{chapter_number}",
        download_status=DownloadStatus.done,
        is_active=is_active,
        relocation_status=RelocationStatus.done,
        chapter_published_at=published_at,
    )
    db.add(a)
    await db.commit()
    return a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_none_with_no_chapters(db_session):
    comic = await _make_comic(db_session)
    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_with_one_chapter(db_session):
    comic = await _make_comic(db_session)
    source = await _make_source(db_session)
    await _add_chapter(db_session, comic, source, chapter_number=1, published_at=_T0)
    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_returns_correct_median_for_regular_chapters(db_session):
    """Five chapters released exactly 7 days apart → cadence should be 7.0."""
    comic = await _make_comic(db_session)
    source = await _make_source(db_session)
    for i in range(5):
        await _add_chapter(
            db_session, comic, source,
            chapter_number=float(i + 1),
            published_at=_T0 + timedelta(days=7 * i),
        )
    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is not None
    assert abs(result - 7.0) < 0.01


@pytest.mark.asyncio
async def test_hiatus_gap_is_filtered(db_session):
    """Chapters at days 0, 7, 14 then a 90-day hiatus then 97, 104.
    The 90-day gap is > 3× initial median (7d) and should be discarded.
    Filtered median of [7, 7, 7, 7] = 7.0.
    """
    comic = await _make_comic(db_session)
    source = await _make_source(db_session)
    dates = [0, 7, 14, 104, 111, 118]  # hiatus between day 14 and 104 = 90 days
    for i, offset in enumerate(dates):
        await _add_chapter(
            db_session, comic, source,
            chapter_number=float(i + 1),
            published_at=_T0 + timedelta(days=offset),
        )
    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is not None
    assert abs(result - 7.0) < 0.01


@pytest.mark.asyncio
async def test_all_sub_day_gaps_returns_none(db_session):
    """Three chapters released 1 hour apart — all gaps are ~0.041 days, well under 1 day.
    infer_cadence should return None so callers fall back to DEFAULT_POLL_DAYS."""
    comic = await _make_comic(db_session)
    source = await _make_source(db_session)
    for i in range(3):
        await _add_chapter(
            db_session, comic, source,
            chapter_number=float(i + 1),
            published_at=_T0 + timedelta(hours=i),
        )
    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_sub_day_median_after_hiatus_filter_returns_none(db_session):
    """Six chapters 6 hours apart (gaps = 0.25d each), then one 30-day gap.
    Initial median = 0.25d → hiatus threshold = 0.75d → 30-day gap is filtered.
    Filtered median = 0.25d < 1.0 → should return None."""
    comic = await _make_comic(db_session)
    source = await _make_source(db_session)
    # Six chapters 6 hours apart, then one more 30 days later
    offsets = [timedelta(hours=6 * i) for i in range(6)] + [timedelta(hours=30, days=30)]
    for i, offset in enumerate(offsets):
        await _add_chapter(
            db_session, comic, source,
            chapter_number=float(i + 1),
            published_at=_T0 + offset,
        )
    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_exactly_one_day_cadence_is_accepted(db_session):
    """Chapters released exactly 1 day apart should be returned as-is (boundary: >= 1.0)."""
    comic = await _make_comic(db_session)
    source = await _make_source(db_session)
    for i in range(4):
        await _add_chapter(
            db_session, comic, source,
            chapter_number=float(i + 1),
            published_at=_T0 + timedelta(days=i),
        )
    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is not None
    assert abs(result - 1.0) < 0.001


@pytest.mark.asyncio
async def test_sub_day_gaps_surviving_hiatus_filter_are_floored(db_session):
    """Four chapters 30 minutes apart — no hiatus, all gaps survive the filter.
    Median is ~0.021 days, which should return None."""
    comic = await _make_comic(db_session)
    source = await _make_source(db_session)
    for i in range(4):
        await _add_chapter(
            db_session, comic, source,
            chapter_number=float(i + 1),
            published_at=_T0 + timedelta(minutes=30 * i),
        )
    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_inactive_chapters_are_ignored(db_session):
    """Inactive chapters (superseded upgrades) should not affect cadence."""
    comic = await _make_comic(db_session)
    source = await _make_source(db_session)
    # Two active chapters 7 days apart
    await _add_chapter(db_session, comic, source, chapter_number=1, published_at=_T0, is_active=True)
    await _add_chapter(db_session, comic, source, chapter_number=2, published_at=_T0 + timedelta(days=7), is_active=True)
    # One inactive chapter with a different date — should be ignored
    await _add_chapter(db_session, comic, source, chapter_number=1, published_at=_T0 + timedelta(days=100), is_active=False)

    result = await cadence_inferrer.infer_cadence(comic.id, db_session)
    assert result is not None
    assert abs(result - 7.0) < 0.01
