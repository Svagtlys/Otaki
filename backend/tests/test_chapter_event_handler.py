from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.models.chapter_assignment import (
    ChapterAssignment,
    DownloadStatus,
    RelocationStatus,
)
from app.models.comic import Comic, ComicStatus
from app.models.source import Source
from app.workers import chapter_event_handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def handler_db(monkeypatch):
    """In-memory SQLite DB with the handler's AsyncSessionLocal patched to use it.

    Yields the session factory so individual tests can open sessions to seed
    data and verify state after calling handle().
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        from app import models  # noqa: F401

        await conn.run_sync(database.Base.metadata.create_all)

    monkeypatch.setattr(chapter_event_handler, "AsyncSessionLocal", session_factory)

    yield session_factory

    await engine.dispose()


@pytest.fixture
def mock_relocator(monkeypatch):
    """Replaces the file_relocator module inside the handler with AsyncMock stubs."""
    mock = MagicMock()
    mock.relocate = AsyncMock()
    mock.replace_in_library = AsyncMock()
    monkeypatch.setattr(chapter_event_handler, "file_relocator", mock)
    return mock


@pytest.fixture
def mock_scheduler_module(monkeypatch):
    """Replaces scheduler_module inside the handler so add_job calls are captured."""
    mock = MagicMock()
    monkeypatch.setattr(chapter_event_handler, "scheduler_module", mock)
    return mock


@pytest.fixture
def mock_suwayomi(monkeypatch):
    """Replaces the suwayomi service inside the handler."""
    mock = MagicMock()
    mock.enqueue_downloads = AsyncMock()
    monkeypatch.setattr(chapter_event_handler, "suwayomi", mock)
    return mock


async def _seed_comic(session_factory) -> tuple[Comic, Source]:
    async with session_factory() as db:
        source = Source(
            suwayomi_source_id="src-1",
            name="Test Source",
            priority=1,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(source)
        await db.flush()

        comic = Comic(
            title="Test Comic",
            library_title="Test Comic",
            status=ComicStatus.tracking,
            created_at=datetime.now(UTC),
        )
        db.add(comic)
        await db.flush()
        await db.commit()

        # Refresh to get IDs
        await db.refresh(source)
        await db.refresh(comic)
        return comic.id, source.id


def _make_assignment(comic_id, source_id, *, chapter_id, is_active, chapter_number=1.0, retry_count=0):
    return ChapterAssignment(
        comic_id=comic_id,
        chapter_number=chapter_number,
        source_id=source_id,
        suwayomi_manga_id="manga-1",
        suwayomi_chapter_id=chapter_id,
        download_status=DownloadStatus.downloading,
        is_active=is_active,
        chapter_published_at=datetime.now(UTC),
        relocation_status=RelocationStatus.pending,
        retry_count=retry_count,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_unknown_chapter_id(handler_db, mock_relocator):
    """handle() logs a warning and returns without error for an unknown chapter ID."""
    await chapter_event_handler.handle("FINISHED", "does-not-exist", "Chapter 1", "Unknown Manga", "TestSrc")

    mock_relocator.relocate.assert_not_called()
    mock_relocator.replace_in_library.assert_not_called()


@pytest.mark.asyncio
async def test_handle_regular_download(handler_db, mock_relocator):
    """Regular first download: relocate() called, assignment marked done and active."""
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        assignment = _make_assignment(
            comic_id, source_id, chapter_id="ch-1", is_active=False
        )
        db.add(assignment)
        await db.commit()
        assignment_id = assignment.id

    await chapter_event_handler.handle("FINISHED", "ch-1", "Chapter 1", "Test Comic", "TestSrc")

    mock_relocator.relocate.assert_awaited_once()
    mock_relocator.replace_in_library.assert_not_called()

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.download_status == DownloadStatus.done
        assert result.downloaded_at is not None
        assert result.is_active is True


@pytest.mark.asyncio
async def test_handle_upgrade_download(handler_db, mock_relocator):
    """Upgrade download: replace_in_library() called, old deactivated, new activated."""
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        old = _make_assignment(comic_id, source_id, chapter_id="ch-old", is_active=True)
        new = _make_assignment(
            comic_id, source_id, chapter_id="ch-new", is_active=False
        )
        db.add_all([old, new])
        await db.commit()
        old_id, new_id = old.id, new.id

    await chapter_event_handler.handle("FINISHED", "ch-new", "Chapter 1", "Test Comic", "TestSrc")

    mock_relocator.replace_in_library.assert_awaited_once()
    mock_relocator.relocate.assert_not_called()

    async with handler_db() as db:
        old_row = await db.get(ChapterAssignment, old_id)
        new_row = await db.get(ChapterAssignment, new_id)
        assert old_row.is_active is False
        assert new_row.is_active is True
        assert new_row.download_status == DownloadStatus.done
        assert new_row.downloaded_at is not None


@pytest.mark.asyncio
async def test_handle_upgrade_always_swaps(handler_db, mock_relocator):
    """For 1.0 (no quality scanner), upgrade always swaps regardless of source quality."""
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        old = _make_assignment(
            comic_id, source_id, chapter_id="ch-old-2", is_active=True
        )
        new = _make_assignment(
            comic_id, source_id, chapter_id="ch-new-2", is_active=False
        )
        db.add_all([old, new])
        await db.commit()
        old_id, new_id = old.id, new.id

    # No severity comparison in 1.0 — swap always happens.
    await chapter_event_handler.handle("FINISHED", "ch-new-2", "Chapter 1", "Test Comic", "TestSrc")

    mock_relocator.replace_in_library.assert_awaited_once()

    async with handler_db() as db:
        assert (await db.get(ChapterAssignment, old_id)).is_active is False
        assert (await db.get(ChapterAssignment, new_id)).is_active is True


# ---------------------------------------------------------------------------
# Retry tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_error_unknown_chapter_id(handler_db, mock_scheduler_module):
    """ERROR event for unknown chapter ID logs a warning and does not schedule a job."""
    await chapter_event_handler.handle("ERROR", "does-not-exist", "Ch 1", "Manga", "Src")
    mock_scheduler_module.scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_handle_error_first_retry_schedules_job(handler_db, mock_scheduler_module, monkeypatch):
    """First ERROR: retry_count→1, status=failed, job scheduled ~300s out."""
    monkeypatch.setattr(chapter_event_handler.settings, "MAX_DOWNLOAD_RETRIES", 2)
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(comic_id, source_id, chapter_id="ch-err-1", is_active=True)
        db.add(a)
        await db.commit()
        assignment_id = a.id

    before = datetime.now(UTC)
    await chapter_event_handler.handle("ERROR", "ch-err-1", "Ch 1", "Manga", "Src")

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.download_status == DownloadStatus.failed
        assert result.retry_count == 1

    mock_scheduler_module.scheduler.add_job.assert_called_once()
    call_kwargs = mock_scheduler_module.scheduler.add_job.call_args.kwargs
    assert call_kwargs["trigger"] == "date"
    assert call_kwargs["id"] == f"retry_download_{assignment_id}_1"
    run_date = call_kwargs["run_date"]
    assert run_date >= before + timedelta(seconds=290)
    assert run_date <= before + timedelta(seconds=310)


@pytest.mark.asyncio
async def test_handle_error_second_retry_doubled_delay(handler_db, mock_scheduler_module, monkeypatch):
    """Second ERROR: retry_count→2, job scheduled ~600s out."""
    monkeypatch.setattr(chapter_event_handler.settings, "MAX_DOWNLOAD_RETRIES", 2)
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(comic_id, source_id, chapter_id="ch-err-2", is_active=True, retry_count=1)
        a.download_status = DownloadStatus.failed
        db.add(a)
        await db.commit()
        assignment_id = a.id

    before = datetime.now(UTC)
    await chapter_event_handler.handle("ERROR", "ch-err-2", "Ch 1", "Manga", "Src")

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.retry_count == 2

    call_kwargs = mock_scheduler_module.scheduler.add_job.call_args.kwargs
    run_date = call_kwargs["run_date"]
    assert run_date >= before + timedelta(seconds=590)
    assert run_date <= before + timedelta(seconds=610)


@pytest.mark.asyncio
async def test_handle_error_exhausts_retries(handler_db, mock_scheduler_module, monkeypatch):
    """ERROR after MAX_DOWNLOAD_RETRIES: permanently failed, no job scheduled."""
    monkeypatch.setattr(chapter_event_handler.settings, "MAX_DOWNLOAD_RETRIES", 2)
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(comic_id, source_id, chapter_id="ch-err-3", is_active=True, retry_count=2)
        a.download_status = DownloadStatus.failed
        db.add(a)
        await db.commit()
        assignment_id = a.id

    await chapter_event_handler.handle("ERROR", "ch-err-3", "Ch 1", "Manga", "Src")

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.retry_count == 3
        assert result.download_status == DownloadStatus.failed

    mock_scheduler_module.scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_retry_download_reenqueues_chapter(handler_db, mock_suwayomi):
    """_retry_download sets status=queued and calls enqueue_downloads."""
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(comic_id, source_id, chapter_id="ch-retry-1", is_active=True)
        a.download_status = DownloadStatus.failed
        db.add(a)
        await db.commit()
        assignment_id = a.id

    await chapter_event_handler._retry_download(assignment_id, "ch-retry-1")

    mock_suwayomi.enqueue_downloads.assert_awaited_once_with(["ch-retry-1"])

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.download_status == DownloadStatus.queued


@pytest.mark.asyncio
async def test_retry_download_skips_non_failed(handler_db, mock_suwayomi):
    """_retry_download does nothing if the assignment is not in failed state."""
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(comic_id, source_id, chapter_id="ch-retry-2", is_active=True)
        a.download_status = DownloadStatus.done
        db.add(a)
        await db.commit()
        assignment_id = a.id

    await chapter_event_handler._retry_download(assignment_id, "ch-retry-2")

    mock_suwayomi.enqueue_downloads.assert_not_called()


@pytest.mark.asyncio
async def test_retry_download_reverts_on_enqueue_failure(handler_db, mock_suwayomi):
    """If enqueue_downloads raises, download_status reverts to failed."""
    mock_suwayomi.enqueue_downloads.side_effect = Exception("network error")
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(comic_id, source_id, chapter_id="ch-retry-3", is_active=True)
        a.download_status = DownloadStatus.failed
        db.add(a)
        await db.commit()
        assignment_id = a.id

    await chapter_event_handler._retry_download(assignment_id, "ch-retry-3")

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.download_status == DownloadStatus.failed
