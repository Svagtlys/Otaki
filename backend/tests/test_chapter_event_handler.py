from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from app import database
from app.models.chapter_assignment import (
    ChapterAssignment,
    DownloadStatus,
    RelocationStatus,
)
from app.models.comic import Comic, ComicStatus
from app.models.source import Source
from app.workers import chapter_event_handler
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def handler_db(monkeypatch):
    """In-memory SQLite DB with the handler's write_session patched to use it.

    Yields the session factory so individual tests can open sessions to seed
    data and verify state after calling handle().

    Both write_session and AsyncSessionLocal are patched so that Phase 2
    (which bypasses the asyncio lock) still uses the in-memory test DB.
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

    monkeypatch.setattr(chapter_event_handler, "write_session", _write_session_stub)
    # Phase 2 bypasses write_session() and uses AsyncSessionLocal() directly.
    # Patch it to use the test session factory instead of the production DB.
    monkeypatch.setattr(
        chapter_event_handler, "AsyncSessionLocal", session_factory, raising=False
    )

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


def _make_assignment(
    comic_id, source_id, *, chapter_id, is_active, chapter_number=1.0, retry_count=0
):
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
    await chapter_event_handler.handle(
        "FINISHED", "does-not-exist", "Chapter 1", "Unknown Manga", "TestSrc"
    )

    mock_relocator.relocate.assert_not_called()
    mock_relocator.replace_in_library.assert_not_called()


@pytest.mark.asyncio
async def test_handle_duplicate_finished_ignored(handler_db, mock_relocator):
    """Duplicate FINISHED event for an already-done assignment is silently ignored."""
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(comic_id, source_id, chapter_id="ch-dup", is_active=True)
        a.download_status = DownloadStatus.done
        db.add(a)
        await db.commit()

    await chapter_event_handler.handle(
        "FINISHED", "ch-dup", "Chapter 1", "Test Comic", "TestSrc"
    )

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

    await chapter_event_handler.handle(
        "FINISHED", "ch-1", "Chapter 1", "Test Comic", "TestSrc"
    )

    mock_relocator.relocate.assert_awaited_once()
    mock_relocator.replace_in_library.assert_not_called()

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.download_status == DownloadStatus.done
        assert result.downloaded_at is not None
        assert result.is_active is True


@pytest.mark.asyncio
async def test_handle_three_phase_intermediate_state(handler_db, monkeypatch):
    """Phase 1 should commit download_status=done before file I/O runs."""
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        assignment = _make_assignment(
            comic_id, source_id, chapter_id="ch-three-phase", is_active=False
        )
        db.add(assignment)
        await db.commit()
        assignment_id = assignment.id

    # Patch file_relocator.relocate to verify Phase 1 committed before file I/O
    phase1_committed = False

    async def tracking_relocate(*args, **kwargs):
        nonlocal phase1_committed
        # At this point, Phase 1 should have committed download_status=done
        async with handler_db() as verify_db:
            a = await verify_db.get(ChapterAssignment, assignment_id)
            assert a.download_status == DownloadStatus.done
            # is_active should NOT be set yet — file I/O hasn't completed
            assert a.is_active is False
            phase1_committed = True

    monkeypatch.setattr(
        chapter_event_handler.file_relocator, "relocate", tracking_relocate
    )

    await chapter_event_handler.handle(
        "FINISHED", "ch-three-phase", "Chapter 1", "Test Comic", "TestSrc"
    )

    assert phase1_committed is True

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.download_status == DownloadStatus.done
        assert result.is_active is True


@pytest.mark.asyncio
async def test_handle_upgrade_download(handler_db, mock_relocator):
    """Upgrade download: replace_in_library() called, old deactivated, new activated."""
    async with handler_db() as db:
        # Old assignment from lower-priority source
        old_source = Source(
            suwayomi_source_id="src-old-upgrade",
            name="Old Source",
            priority=10,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(old_source)
        # New assignment from higher-priority source
        new_source = Source(
            suwayomi_source_id="src-new-upgrade",
            name="New Source",
            priority=1,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(new_source)
        await db.flush()

        comic = Comic(
            title="Upgrade Test Comic",
            library_title="Upgrade Test Comic",
            status=ComicStatus.tracking,
            created_at=datetime.now(UTC),
        )
        db.add(comic)
        await db.flush()

        old = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=1.0,
            source_id=old_source.id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id="ch-old",
            download_status=DownloadStatus.done,
            is_active=True,
            chapter_published_at=datetime.now(UTC),
            relocation_status=RelocationStatus.done,
        )
        new = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=1.0,
            source_id=new_source.id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id="ch-new",
            download_status=DownloadStatus.downloading,
            is_active=False,
            chapter_published_at=datetime.now(UTC),
            relocation_status=RelocationStatus.pending,
        )
        db.add_all([old, new])
        await db.commit()
        old_id, new_id = old.id, new.id

    await chapter_event_handler.handle(
        "FINISHED", "ch-new", "Chapter 1", "Upgrade Test Comic", "New Source"
    )

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
    """Higher-priority source always swaps regardless of other factors."""
    async with handler_db() as db:
        # Old assignment from lower-priority source
        old_source = Source(
            suwayomi_source_id="src-old-always",
            name="Old Source Always",
            priority=10,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(old_source)
        # New assignment from higher-priority source
        new_source = Source(
            suwayomi_source_id="src-new-always",
            name="New Source Always",
            priority=1,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(new_source)
        await db.flush()

        comic = Comic(
            title="Always Swap Comic",
            library_title="Always Swap Comic",
            status=ComicStatus.tracking,
            created_at=datetime.now(UTC),
        )
        db.add(comic)
        await db.flush()

        old = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=1.0,
            source_id=old_source.id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id="ch-old-2",
            download_status=DownloadStatus.done,
            is_active=True,
            chapter_published_at=datetime.now(UTC),
            relocation_status=RelocationStatus.done,
        )
        new = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=1.0,
            source_id=new_source.id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id="ch-new-2",
            download_status=DownloadStatus.downloading,
            is_active=False,
            chapter_published_at=datetime.now(UTC),
            relocation_status=RelocationStatus.pending,
        )
        db.add_all([old, new])
        await db.commit()
        old_id, new_id = old.id, new.id

    await chapter_event_handler.handle(
        "FINISHED", "ch-new-2", "Chapter 1", "Always Swap Comic", "New Source Always"
    )

    mock_relocator.replace_in_library.assert_awaited_once()

    async with handler_db() as db:
        assert (await db.get(ChapterAssignment, old_id)).is_active is False
        assert (await db.get(ChapterAssignment, new_id)).is_active is True


# ---------------------------------------------------------------------------
# Priority-aware upgrade swap tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_upgrade_lower_priority_no_swap(handler_db, mock_relocator):
    """Incoming from lower-priority source should NOT swap out existing active."""
    async with handler_db() as db:
        # High priority source (lower number = higher priority)
        high_source = Source(
            suwayomi_source_id="src-high",
            name="High Priority",
            priority=1,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(high_source)
        # Low priority source
        low_source = Source(
            suwayomi_source_id="src-low",
            name="Low Priority",
            priority=10,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(low_source)
        await db.flush()

        comic = Comic(
            title="Priority Test Comic",
            library_title="Priority Test Comic",
            status=ComicStatus.tracking,
            created_at=datetime.now(UTC),
        )
        db.add(comic)
        await db.flush()

        # Existing active from high-priority source
        existing = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=1.0,
            source_id=high_source.id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id="ch-high",
            download_status=DownloadStatus.done,
            is_active=True,
            chapter_published_at=datetime.now(UTC),
            relocation_status=RelocationStatus.done,
        )
        db.add(existing)

        # Incoming from low-priority source
        incoming = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=1.0,
            source_id=low_source.id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id="ch-low",
            download_status=DownloadStatus.downloading,
            is_active=False,
            chapter_published_at=datetime.now(UTC),
            relocation_status=RelocationStatus.pending,
        )
        db.add(incoming)
        await db.commit()
        existing_id = existing.id
        incoming_id = incoming.id

    await chapter_event_handler.handle(
        "FINISHED", "ch-low", "Chapter 1", "Priority Test Comic", "Low Priority"
    )

    # replace_in_library should NOT be called
    mock_relocator.replace_in_library.assert_not_called()
    mock_relocator.relocate.assert_not_called()

    async with handler_db() as db:
        existing_row = await db.get(ChapterAssignment, existing_id)
        incoming_row = await db.get(ChapterAssignment, incoming_id)
        # High-priority source should remain active
        assert existing_row.is_active is True
        # Incoming should be marked done but NOT active
        assert incoming_row.is_active is False
        assert incoming_row.download_status == DownloadStatus.done


@pytest.mark.asyncio
async def test_handle_upgrade_existing_failed_always_swaps(handler_db, mock_relocator):
    """Even lower-priority source should swap if existing active has failed."""
    async with handler_db() as db:
        # High priority source (lower number = higher priority)
        high_source = Source(
            suwayomi_source_id="src-high-2",
            name="High Priority",
            priority=1,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(high_source)
        # Low priority source
        low_source = Source(
            suwayomi_source_id="src-low-2",
            name="Low Priority",
            priority=10,
            enabled=True,
            created_at=datetime.now(UTC),
        )
        db.add(low_source)
        await db.flush()

        comic = Comic(
            title="Failed Swap Comic",
            library_title="Failed Swap Comic",
            status=ComicStatus.tracking,
            created_at=datetime.now(UTC),
        )
        db.add(comic)
        await db.flush()

        # Existing active from high-priority source but DOWNLOAD FAILED
        existing = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=1.0,
            source_id=high_source.id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id="ch-high-fail",
            download_status=DownloadStatus.failed,
            is_active=True,
            chapter_published_at=datetime.now(UTC),
            relocation_status=RelocationStatus.pending,
        )
        db.add(existing)

        # Incoming from low-priority source
        incoming = ChapterAssignment(
            comic_id=comic.id,
            chapter_number=1.0,
            source_id=low_source.id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id="ch-low-success",
            download_status=DownloadStatus.downloading,
            is_active=False,
            chapter_published_at=datetime.now(UTC),
            relocation_status=RelocationStatus.pending,
        )
        db.add(incoming)
        await db.commit()
        existing_id = existing.id
        incoming_id = incoming.id

    await chapter_event_handler.handle(
        "FINISHED", "ch-low-success", "Chapter 1", "Failed Swap Comic", "Low Priority"
    )

    # Should swap because existing is failed
    mock_relocator.replace_in_library.assert_awaited_once()

    async with handler_db() as db:
        existing_row = await db.get(ChapterAssignment, existing_id)
        incoming_row = await db.get(ChapterAssignment, incoming_id)
        assert existing_row.is_active is False
        assert incoming_row.is_active is True


# ---------------------------------------------------------------------------
# Retry tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_error_unknown_chapter_id(handler_db, mock_scheduler_module):
    """ERROR event for unknown chapter ID logs a warning and does not schedule a job."""
    await chapter_event_handler.handle(
        "ERROR", "does-not-exist", "Ch 1", "Manga", "Src"
    )
    mock_scheduler_module.scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_handle_error_first_retry_schedules_job(
    handler_db, mock_scheduler_module, monkeypatch
):
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
async def test_handle_error_second_retry_doubled_delay(
    handler_db, mock_scheduler_module, monkeypatch
):
    """Second ERROR: retry_count→2, job scheduled ~600s out."""
    monkeypatch.setattr(chapter_event_handler.settings, "MAX_DOWNLOAD_RETRIES", 2)
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(
            comic_id, source_id, chapter_id="ch-err-2", is_active=True, retry_count=1
        )
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
async def test_handle_error_exhausts_retries(
    handler_db, mock_scheduler_module, monkeypatch
):
    """ERROR after MAX_DOWNLOAD_RETRIES: permanently failed, no job scheduled."""
    monkeypatch.setattr(chapter_event_handler.settings, "MAX_DOWNLOAD_RETRIES", 2)
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a = _make_assignment(
            comic_id, source_id, chapter_id="ch-err-3", is_active=True, retry_count=2
        )
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
        a = _make_assignment(
            comic_id, source_id, chapter_id="ch-retry-1", is_active=True
        )
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
        a = _make_assignment(
            comic_id, source_id, chapter_id="ch-retry-2", is_active=True
        )
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
        a = _make_assignment(
            comic_id, source_id, chapter_id="ch-retry-3", is_active=True
        )
        a.download_status = DownloadStatus.failed
        db.add(a)
        await db.commit()
        assignment_id = a.id

    await chapter_event_handler._retry_download(assignment_id, "ch-retry-3")

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.download_status == DownloadStatus.failed


# ---------------------------------------------------------------------------
# Concurrency test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_concurrent_calls_do_not_raise(handler_db, mock_relocator):
    """Two handle() calls dispatched concurrently both complete without error.

    Validates that write_session() serialises DB writes so neither task fails
    with a lock error even when they run concurrently via asyncio.gather.
    """
    import asyncio

    from sqlalchemy import select

    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        a1 = _make_assignment(
            comic_id,
            source_id,
            chapter_id="ch-conc-1",
            is_active=False,
            chapter_number=1.0,
        )
        a2 = _make_assignment(
            comic_id,
            source_id,
            chapter_id="ch-conc-2",
            is_active=False,
            chapter_number=2.0,
        )
        db.add_all([a1, a2])
        await db.commit()

    await asyncio.gather(
        chapter_event_handler.handle(
            "FINISHED", "ch-conc-1", "Ch 1", "Test Comic", "TestSource"
        ),
        chapter_event_handler.handle(
            "FINISHED", "ch-conc-2", "Ch 2", "Test Comic", "TestSource"
        ),
    )

    async with handler_db() as db:
        r1 = await db.scalar(
            select(ChapterAssignment).where(
                ChapterAssignment.suwayomi_chapter_id == "ch-conc-1"
            )
        )
        r2 = await db.scalar(
            select(ChapterAssignment).where(
                ChapterAssignment.suwayomi_chapter_id == "ch-conc-2"
            )
        )

    assert r1.download_status == DownloadStatus.done
    assert r1.is_active is True
    assert r2.download_status == DownloadStatus.done
    assert r2.is_active is True
