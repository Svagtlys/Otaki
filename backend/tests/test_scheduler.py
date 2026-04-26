"""Unit and integration tests for workers/scheduler.py."""

from contextlib import asynccontextmanager
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
from app.services import suwayomi as suwayomi_module
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
    """In-memory SQLite with write_session patched into the scheduler module.

    Also patches scheduler.add_job and scheduler.start so no real APScheduler
    state is mutated during tests.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        from app import models  # noqa: F401

        await conn.run_sync(database.Base.metadata.create_all)

    @asynccontextmanager
    async def _write_session_stub():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(scheduler_module, "write_session", _write_session_stub)

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
    monkeypatch.setattr(
        scheduler_module.source_selector, "build_chapter_source_map", mock_map
    )
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
        return {1.0: (fake_source, "manga-1", {
            "chapter_number": 1.0,
            "volume_number": None,
            "suwayomi_chapter_id": "ch-1",
            "chapter_published_at": datetime(2024, 1, 1, tzinfo=UTC),
        })}

    mock_enqueue = AsyncMock()
    monkeypatch.setattr(
        scheduler_module.source_selector, "build_chapter_source_map", fake_build_map
    )
    monkeypatch.setattr(scheduler_module.suwayomi, "enqueue_downloads", mock_enqueue)

    await scheduler_module._poll_comic(comic_id)

    mock_enqueue.assert_not_called()


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
        return {2.0: (fake_source, "manga-1", {
            "chapter_number": 2.0,
            "volume_number": None,
            "suwayomi_chapter_id": "ch-2",
            "chapter_published_at": published,
        })}

    mock_enqueue = AsyncMock()
    monkeypatch.setattr(
        scheduler_module.source_selector, "build_chapter_source_map", fake_build_map
    )
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
    assert rows[0].chapter_published_at == published.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_poll_advances_next_poll_at(sched_db, monkeypatch):
    """_poll_comic updates comic.next_poll_at to ~7 days from now after running."""
    before = datetime.now()

    async with sched_db() as db:
        comic = _make_comic()
        db.add(comic)
        await db.commit()
        comic_id = comic.id

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())

    async def fake_build_map(comic, db):
        return {}

    monkeypatch.setattr(
        scheduler_module.source_selector, "build_chapter_source_map", fake_build_map
    )

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
    assert f"upgrade_{id1}" in registered_ids
    assert f"upgrade_{id2}" in registered_ids


@pytest.mark.asyncio
async def test_register_comic_jobs_registers_both(monkeypatch):
    """register_comic_jobs registers both poll and upgrade jobs."""
    comic = _make_comic()
    comic.id = 99

    registered_ids: list[str] = []

    def fake_add_job(*args, **kwargs):
        registered_ids.append(kwargs.get("id", ""))

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", fake_add_job)

    scheduler_module.register_comic_jobs(comic)

    assert "poll_99" in registered_ids
    assert "upgrade_99" in registered_ids


@pytest.mark.asyncio
async def test_upgrade_skips_complete_comic(sched_db, monkeypatch):
    """_upgrade_comic does nothing for a comic with status=complete."""
    async with sched_db() as db:
        comic = _make_comic(status=ComicStatus.complete)
        db.add(comic)
        await db.commit()
        comic_id = comic.id

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())
    mock_candidates = AsyncMock()
    monkeypatch.setattr(
        scheduler_module.source_selector, "find_upgrade_candidates", mock_candidates
    )

    await scheduler_module._upgrade_comic(comic_id)

    mock_candidates.assert_not_called()


@pytest.mark.asyncio
async def test_upgrade_no_candidates(sched_db, monkeypatch):
    """_upgrade_comic advances timestamps even when no upgrade candidates are found."""
    async with sched_db() as db:
        comic = _make_comic()
        db.add(comic)
        await db.commit()
        comic_id = comic.id

    before = datetime.now()
    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())
    monkeypatch.setattr(
        scheduler_module.source_selector,
        "find_upgrade_candidates",
        AsyncMock(return_value=[]),
    )
    mock_enqueue = AsyncMock()
    monkeypatch.setattr(scheduler_module.suwayomi, "enqueue_downloads", mock_enqueue)

    await scheduler_module._upgrade_comic(comic_id)

    mock_enqueue.assert_not_called()

    async with sched_db() as db:
        comic = await db.get(Comic, comic_id)

    assert comic.last_upgrade_check_at is not None
    assert comic.next_upgrade_check_at is not None
    assert comic.next_upgrade_check_at >= before + timedelta(days=6, hours=23)


@pytest.mark.asyncio
async def test_upgrade_creates_assignment_and_enqueues(sched_db, monkeypatch):
    """_upgrade_comic creates a new inactive assignment and enqueues it."""
    async with sched_db() as db:
        source_a = _make_source()
        db.add(source_a)
        await db.flush()

        source_b = Source(
            suwayomi_source_id="src-2",
            name="Better Source",
            priority=1,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(source_b)
        await db.flush()

        comic = _make_comic()
        db.add(comic)
        await db.flush()

        assignment = _make_assignment(comic.id, source_a.id, chapter_number=1.0)
        db.add(assignment)
        await db.commit()
        comic_id = comic.id
        source_b_id = source_b.id

    published = datetime(2024, 6, 1, tzinfo=UTC)
    fake_source_b = MagicMock()
    fake_source_b.id = source_b_id

    fake_assignment = MagicMock()
    fake_assignment.chapter_number = 1.0

    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())
    monkeypatch.setattr(
        scheduler_module.source_selector,
        "find_upgrade_candidates",
        AsyncMock(return_value=[(
            fake_assignment,
            fake_source_b,
            "manga-99",
            {
                "chapter_number": 1.0,
                "volume_number": None,
                "suwayomi_chapter_id": "ch-upgrade-1",
                "chapter_published_at": published,
            },
        )]),
    )
    mock_enqueue = AsyncMock()
    monkeypatch.setattr(scheduler_module.suwayomi, "enqueue_downloads", mock_enqueue)

    await scheduler_module._upgrade_comic(comic_id)

    mock_enqueue.assert_awaited_once_with(["ch-upgrade-1"])

    async with sched_db() as db:
        result = await db.execute(
            select(ChapterAssignment).where(
                ChapterAssignment.comic_id == comic_id,
                ChapterAssignment.is_active.is_(False),
            )
        )
        rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].chapter_number == 1.0
    assert rows[0].source_id == source_b_id
    assert rows[0].suwayomi_chapter_id == "ch-upgrade-1"
    assert rows[0].download_status == DownloadStatus.queued


@pytest.mark.asyncio
async def test_upgrade_uses_upgrade_override_days(sched_db, monkeypatch):
    """_upgrade_comic uses upgrade_override_days when set."""
    async with sched_db() as db:
        comic = Comic(
            title="Test",
            library_title="Test",
            status=ComicStatus.tracking,
            poll_override_days=7,
            upgrade_override_days=14,
            created_at=datetime.now(UTC),
        )
        db.add(comic)
        await db.commit()
        comic_id = comic.id

    before = datetime.now()
    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())
    monkeypatch.setattr(
        scheduler_module.source_selector,
        "find_upgrade_candidates",
        AsyncMock(return_value=[]),
    )

    await scheduler_module._upgrade_comic(comic_id)

    async with sched_db() as db:
        comic = await db.get(Comic, comic_id)

    assert comic.next_upgrade_check_at >= before + timedelta(days=13, hours=23)
    assert comic.next_upgrade_check_at <= before + timedelta(days=14, hours=1)


@pytest.mark.asyncio
async def test_upgrade_falls_back_to_poll_override_days(sched_db, monkeypatch):
    """_upgrade_comic falls back to poll_override_days when upgrade_override_days is None."""
    async with sched_db() as db:
        comic = Comic(
            title="Test",
            library_title="Test",
            status=ComicStatus.tracking,
            poll_override_days=7,
            upgrade_override_days=None,
            created_at=datetime.now(UTC),
        )
        db.add(comic)
        await db.commit()
        comic_id = comic.id

    before = datetime.now()
    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())
    monkeypatch.setattr(
        scheduler_module.source_selector,
        "find_upgrade_candidates",
        AsyncMock(return_value=[]),
    )

    await scheduler_module._upgrade_comic(comic_id)

    async with sched_db() as db:
        comic = await db.get(Comic, comic_id)

    assert comic.next_upgrade_check_at >= before + timedelta(days=6, hours=23)
    assert comic.next_upgrade_check_at <= before + timedelta(days=7, hours=1)


# ---------------------------------------------------------------------------
# Integration test — requires live Suwayomi
# ---------------------------------------------------------------------------

def test_poll_job_has_misfire_grace_time(monkeypatch):
    """_register_poll_job sets misfire_grace_time to 1 hour (3600 seconds)."""
    # Use a dummy comic
    comic = _make_comic()
    comic.id = 123
    # Capture job registration
    captured = {}
    def fake_add_job(*args, **kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(scheduler_module.scheduler, "add_job", fake_add_job)
    # Register
    scheduler_module._register_poll_job(comic)
    assert captured.get("id") == f"poll_{comic.id}"
    assert captured.get("misfire_grace_time") == 3600

@pytest.mark.asyncio
async def test_start_processes_missed_poll(monkeypatch, sched_db):
    """scheduler.start processes overdue poll jobs immediately."""
    past = datetime.now(UTC) - timedelta(days=1)
    async with sched_db() as db:
        comic = _make_comic(next_poll_at=past)
        db.add(comic)
        await db.commit()
        comic_id = comic.id
    # Patch the poll function to record call
    called = []
    async def fake_poll(comic_id_inner):
        called.append(comic_id_inner)
    monkeypatch.setattr(scheduler_module, "_poll_comic", fake_poll)
    # Patch add_job to avoid APScheduler side effects
    monkeypatch.setattr(scheduler_module.scheduler, "add_job", lambda *a, **kw: None)
    # Run start
    async with sched_db() as db:
        await scheduler_module.start(db)
    assert comic_id in called



@pytest.mark.integration
@pytest.mark.asyncio
async def test_upgrade_comic_integration(sched_db, suwayomi_settings, test_manga_title, monkeypatch):
    """_upgrade_comic creates inactive upgrade assignments when a better-priority source has the chapter.

    Requires at least two Suwayomi sources that both return results for TEST_MANGA_TITLE.
    Skipped automatically if that condition is not met.
    """
    monkeypatch.setattr(scheduler_module.scheduler, "add_job", MagicMock())

    # Find two sources that both have the manga
    all_sources = await suwayomi_module.list_sources()
    sources_with_manga: list[tuple[dict, str, str]] = []  # (source_info, manga_id, title)
    for src in all_sources:
        results = await suwayomi_module.search_source(src["id"], test_manga_title)
        if results:
            sources_with_manga.append((src, results[0]["manga_id"], results[0]["title"]))
        if len(sources_with_manga) == 2:
            break

    if len(sources_with_manga) < 2:
        pytest.skip("Need at least 2 sources that have the test manga for upgrade integration test")

    (src_a_info, manga_id_a, title_a), (src_b_info, manga_id_b, _) = sources_with_manga

    # Seed source A at priority=1 (better), source B at priority=2 (worse)
    async with sched_db() as db:
        source_a = Source(
            suwayomi_source_id=src_a_info["id"],
            name=src_a_info["name"],
            priority=1,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        source_b = Source(
            suwayomi_source_id=src_b_info["id"],
            name=src_b_info["name"],
            priority=2,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add_all([source_a, source_b])
        await db.flush()

        comic = Comic(
            title=title_a,
            library_title=title_a,
            status=ComicStatus.tracking,
            poll_override_days=7,
            created_at=datetime.now(UTC),
        )
        db.add(comic)
        await db.flush()

        # Get chapters from source A to know real chapter numbers
        chapters_a = await suwayomi_module.fetch_chapters(manga_id_a)
        if not chapters_a:
            pytest.skip("Source A returned no chapters")

        # Create active assignments on source B for the first chapter
        ch = chapters_a[0]
        assignment = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=ch["chapter_number"],
            source_id=source_b.id,
            suwayomi_manga_id=manga_id_b,
            suwayomi_chapter_id=ch["suwayomi_chapter_id"],
            download_status=DownloadStatus.done,
            is_active=True,
            chapter_published_at=ch["chapter_published_at"],
        )
        db.add(assignment)
        await db.commit()
        comic_id = comic.id

    await scheduler_module._upgrade_comic(comic_id)

    async with sched_db() as db:
        result = await db.execute(
            select(ChapterAssignment).where(
                ChapterAssignment.comic_id == comic_id,
                ChapterAssignment.is_active.is_(False),
            )
        )
        upgrade_rows = result.scalars().all()

        comic_row = await db.get(Comic, comic_id)

    assert len(upgrade_rows) >= 1
    assert all(r.source_id == source_a.id for r in upgrade_rows)
    assert all(r.download_status == DownloadStatus.queued for r in upgrade_rows)
    assert comic_row.last_upgrade_check_at is not None
    assert comic_row.next_upgrade_check_at is not None
