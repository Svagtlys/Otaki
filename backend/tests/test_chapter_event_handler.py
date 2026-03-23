from datetime import UTC, datetime
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


def _make_assignment(comic_id, source_id, *, chapter_id, is_active, chapter_number=1.0):
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
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_unknown_chapter_id(handler_db, mock_relocator):
    """handle() logs a warning and returns without error for an unknown chapter ID."""
    await chapter_event_handler.handle("does-not-exist", "Chapter 1", "Unknown Manga", "TestSrc")

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

    await chapter_event_handler.handle("ch-1", "Chapter 1", "Test Comic", "TestSrc")

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

    await chapter_event_handler.handle("ch-new", "Chapter 1", "Test Comic", "TestSrc")

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
    await chapter_event_handler.handle("ch-new-2", "Chapter 1", "Test Comic", "TestSrc")

    mock_relocator.replace_in_library.assert_awaited_once()

    async with handler_db() as db:
        assert (await db.get(ChapterAssignment, old_id)).is_active is False
        assert (await db.get(ChapterAssignment, new_id)).is_active is True
