"""Unit and integration tests for workers/scheduler.py."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.models.chapter_assignment import ChapterAssignment, DownloadStatus
from app.models.comic import Comic, ComicStatus
from app.models.source import Source
from app.workers import scheduler as scheduler_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_comic(*, status=ComicStatus.tracking, next_poll_at=None) -> Comic:
    return Comic(
        title="Test Comic",
        library_title="Test Comic",
        status=status,
        next_poll_at=next_poll_at,
        created_at=datetime.now(UTC),
    )


def _make_source() -> Source:
    return Source(
        suwayomi_source_id="src-1",
        name="Test Source",
        priority=1,
        enabled=True,
        created_at=datetime.now(UTC),
    )


def _make_assignment(comic_id, source_id, *, chapter_number=1.0) -> ChapterAssignment:
    return ChapterAssignment(
        comic_id=comic_id,
        chapter_number=chapter_number,
        source_id=source_id,
        suwayomi_manga_id="manga-1",
        suwayomi_chapter_id=f"ch-{chapter_number}",
        download_status=DownloadStatus.done,
        is_active=True,
        chapter_published_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sched_db(monkeypatch):
    """In-memory SQLite with AsyncSessionLocal patched into the scheduler module.

    Also patches scheduler.add_job and scheduler.start so no real APScheduler
    state is mutated during tests.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        from app import models  # noqa: F401

        await conn.run_sync(database.Base.metadata.create_all)

    monkeypatch.setattr(scheduler_module, "AsyncSessionLocal", session_factory)

    # Prevent the real scheduler from running during unit tests.
    monkeypatch.setattr(scheduler_module.scheduler, "start", lambda: None)

    yield session_factory

    await engine.dispose()


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_skips_complete_comic(sched_db, monkeypatch):
    """_poll_comic does nothing for a comic with status=complete."""
    async with sched_db() as db:
        comic = _make_comic(status=ComicStatus.complete)
        db.add(comic)
        await db.commit()
        comic_id = comic.id

    # Patch add_job so _register_poll_job doesn't fail
    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())

    mock_map = AsyncMock()
    mock_enqueue = AsyncMock()
    monkeypatch.setattr(scheduler_module.source_selector, "build_chapter_source_map", mock_map)
    monkeypatch.setattr(scheduler_module.suwayomi, "enqueue_downloads", mock_enqueue)

    await scheduler_module._poll_comic(comic_id)

    mock_map.assert_not_called()
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_poll_no_new_chapters(sched_db, monkeypatch):
    """_poll_comic does not call enqueue_downloads when all chapters already exist."""
    async with sched_db() as db:
        source = _make_source()
        db.add(source)
        await db.flush()

        comic = _make_comic()
        db.add(comic)
        await db.flush()

        assignment = _make_assignment(comic.id, source.id, chapter_number=1.0)
        db.add(assignment)
        await db.commit()
        comic_id = comic.id
        source_id = source.id

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())

    # Build a detached source-like object for the fake map
    fake_source = MagicMock()
    fake_source.id = source_id

    async def fake_build_map(comic, db):
        return {1.0: (fake_source, "manga-1")}

    mock_enqueue = AsyncMock()
    mock_fetch = AsyncMock()
    monkeypatch.setattr(scheduler_module.source_selector, "build_chapter_source_map", fake_build_map)
    monkeypatch.setattr(scheduler_module.suwayomi, "enqueue_downloads", mock_enqueue)
    monkeypatch.setattr(scheduler_module.suwayomi, "fetch_chapters", mock_fetch)

    await scheduler_module._poll_comic(comic_id)

    mock_enqueue.assert_not_called()
    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_poll_creates_assignments(sched_db, monkeypatch):
    """_poll_comic creates ChapterAssignment rows and calls enqueue_downloads for new chapters."""
    async with sched_db() as db:
        source = _make_source()
        db.add(source)
        await db.flush()

        comic = _make_comic()
        db.add(comic)
        await db.commit()
        comic_id = comic.id
        source_id = source.id

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())

    published = datetime(2024, 1, 15, tzinfo=UTC)

    fake_source = MagicMock()
    fake_source.id = source_id

    async def fake_build_map(comic, db):
        return {2.0: (fake_source, "manga-1")}

    fake_chapters = [
        {
            "chapter_number": 2.0,
            "volume_number": None,
            "suwayomi_chapter_id": "ch-2",
            "chapter_published_at": published,
        }
    ]

    mock_fetch = AsyncMock(return_value=fake_chapters)
    mock_enqueue = AsyncMock()
    monkeypatch.setattr(scheduler_module.source_selector, "build_chapter_source_map", fake_build_map)
    monkeypatch.setattr(scheduler_module.suwayomi, "fetch_chapters", mock_fetch)
    monkeypatch.setattr(scheduler_module.suwayomi, "enqueue_downloads", mock_enqueue)

    await scheduler_module._poll_comic(comic_id)

    mock_enqueue.assert_awaited_once_with(["ch-2"])

    async with sched_db() as db:
        result = await db.execute(
            select(ChapterAssignment).where(ChapterAssignment.comic_id == comic_id)
        )
        rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].chapter_number == 2.0
    assert rows[0].suwayomi_chapter_id == "ch-2"
    assert rows[0].download_status == DownloadStatus.queued
    assert rows[0].is_active is True
    assert rows[0].chapter_published_at == published


@pytest.mark.asyncio
async def test_poll_advances_next_poll_at(sched_db, monkeypatch):
    """_poll_comic updates comic.next_poll_at to ~7 days from now after running."""
    before = datetime.now(UTC)

    async with sched_db() as db:
        comic = _make_comic()
        db.add(comic)
        await db.commit()
        comic_id = comic.id

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())

    async def fake_build_map(comic, db):
        return {}

    monkeypatch.setattr(scheduler_module.source_selector, "build_chapter_source_map", fake_build_map)

    await scheduler_module._poll_comic(comic_id)

    async with sched_db() as db:
        comic = await db.get(Comic, comic_id)

    assert comic.next_poll_at is not None
    assert comic.next_poll_at >= before + timedelta(days=6, hours=23)
    assert comic.next_poll_at <= before + timedelta(days=7, hours=1)


@pytest.mark.asyncio
async def test_start_registers_jobs_for_existing_comics(sched_db, monkeypatch):
    """scheduler.start() registers one poll job per tracking comic."""
    async with sched_db() as db:
        c1 = _make_comic()
        c2 = _make_comic()
        db.add_all([c1, c2])
        await db.commit()
        id1, id2 = c1.id, c2.id

    registered_ids: list[str] = []

    def fake_add_job(*args, **kwargs):
        registered_ids.append(kwargs.get("id", ""))

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", fake_add_job)

    async with sched_db() as db:
        await scheduler_module.start(db)

    assert f"poll_{id1}" in registered_ids
    assert f"poll_{id2}" in registered_ids


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_poll_live_suwayomi(sched_db, monkeypatch, suwayomi_settings, test_manga_title):
    """build_chapter_source_map returns results and enqueue_downloads doesn't raise."""
    from app.services.source_selector import build_chapter_source_map

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())

    async with sched_db() as db:
        source = Source(
            suwayomi_source_id="1998416798",  # MangaDex en
            name="MangaDex",
            priority=1,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(source)
        comic = _make_comic()
        comic.title = test_manga_title
        db.add(comic)
        await db.commit()
        comic_id = comic.id

    async with sched_db() as db:
        comic = await db.get(Comic, comic_id)
        chapter_map = await build_chapter_source_map(comic, db)

    assert isinstance(chapter_map, dict)

    if chapter_map:
        # enqueue_downloads should not raise when given valid chapter IDs
        first_entry = next(iter(chapter_map.values()))
        chapter_id = first_entry[0]  # suwayomi_manga_id is the second element
        try:
            await scheduler_module.suwayomi.enqueue_downloads([str(chapter_id)])
        except Exception as exc:
            pytest.fail(f"enqueue_downloads raised: {exc!r}")
