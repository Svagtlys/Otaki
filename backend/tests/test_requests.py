"""Tests for POST/GET/DELETE /api/requests (issue #13)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from app.models.comic import Comic, ComicStatus
from app.models.source import Source


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _add_source(*, name="Test Source", suwayomi_source_id="src-1", priority=1) -> Source:
    from app import database
    async with database.AsyncSessionLocal() as db:
        source = Source(
            suwayomi_source_id=suwayomi_source_id,
            name=name,
            priority=priority,
            enabled=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        return source


async def _add_comic(*, title="Test Comic", library_title=None) -> Comic:
    from app import database
    async with database.AsyncSessionLocal() as db:
        comic = Comic(
            title=title,
            library_title=library_title or title,
            status=ComicStatus.tracking,
            poll_override_days=7.0,
            created_at=datetime.now(timezone.utc),
            next_poll_at=datetime.now(timezone.utc),
        )
        db.add(comic)
        await db.commit()
        await db.refresh(comic)
        return comic


async def _add_assignment(
    comic_id: int,
    source_id: int,
    *,
    chapter_number: float = 1.0,
    library_path: str | None = None,
) -> ChapterAssignment:
    from app import database
    async with database.AsyncSessionLocal() as db:
        assignment = ChapterAssignment(
            comic_id=comic_id,
            chapter_number=chapter_number,
            source_id=source_id,
            suwayomi_manga_id="manga-1",
            suwayomi_chapter_id=f"ch-{chapter_number}",
            download_status=DownloadStatus.done,
            is_active=True,
            chapter_published_at=datetime.now(timezone.utc),
            library_path=library_path,
            relocation_status=RelocationStatus.done if library_path else RelocationStatus.pending,
        )
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)
        return assignment


# ---------------------------------------------------------------------------
# Unit tests — no live Suwayomi
# ---------------------------------------------------------------------------


async def test_post_creates_comic(logged_in_client, monkeypatch):
    from app.services import source_selector, suwayomi

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value={}))
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    r = await logged_in_client.post("/api/requests", json={"primary_title": "My Manga"})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "My Manga"
    assert data["library_title"] == "My Manga"
    assert data["status"] == "tracking"

    from app import database
    async with database.AsyncSessionLocal() as db:
        result = await db.execute(select(Comic).where(Comic.title == "My Manga"))
        comic = result.scalar_one_or_none()
    assert comic is not None


async def test_post_default_library_title(logged_in_client, monkeypatch):
    from app.services import source_selector, suwayomi

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value={}))
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    r = await logged_in_client.post("/api/requests", json={"primary_title": "Another Manga"})
    assert r.status_code == 201
    assert r.json()["library_title"] == "Another Manga"


async def test_post_duplicate_title_returns_409(logged_in_client, monkeypatch):
    from app.services import source_selector, suwayomi

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value={}))
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    await logged_in_client.post("/api/requests", json={"primary_title": "Dupe Comic"})
    r = await logged_in_client.post("/api/requests", json={"primary_title": "Dupe Comic"})
    assert r.status_code == 409


async def test_post_creates_assignments(logged_in_client, monkeypatch):
    from app import database
    from app.services import source_selector, suwayomi

    source = await _add_source()
    fake_source = MagicMock()
    fake_source.id = source.id

    published = datetime(2024, 3, 1, tzinfo=timezone.utc)

    async def _fake_build_map(comic, db):
        return {1.0: (fake_source, "manga-99", {
            "chapter_number": 1.0,
            "volume_number": None,
            "suwayomi_chapter_id": "ch-1",
            "chapter_published_at": published,
        })}

    monkeypatch.setattr(source_selector, "build_chapter_source_map", _fake_build_map)
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    r = await logged_in_client.post("/api/requests", json={"primary_title": "Chapter Comic"})
    assert r.status_code == 201
    comic_id = r.json()["id"]

    async with database.AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChapterAssignment).where(ChapterAssignment.comic_id == comic_id)
        )
        assignments = result.scalars().all()

    assert len(assignments) == 1
    assert assignments[0].chapter_number == 1.0
    assert assignments[0].suwayomi_chapter_id == "ch-1"
    assert assignments[0].download_status == DownloadStatus.queued
    assert assignments[0].is_active is True


async def test_post_registers_jobs(logged_in_client, monkeypatch):
    from app.services import source_selector, suwayomi
    from app.workers import scheduler

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value={}))
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    registered = []
    monkeypatch.setattr(scheduler, "register_comic_jobs", lambda comic: registered.append(comic))

    r = await logged_in_client.post("/api/requests", json={"primary_title": "Job Comic"})
    assert r.status_code == 201
    assert len(registered) == 1
    assert registered[0].title == "Job Comic"


async def test_post_sets_next_poll_at(logged_in_client, monkeypatch):
    from app.services import source_selector, suwayomi

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value={}))
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    before = datetime.now(timezone.utc)
    r = await logged_in_client.post("/api/requests", json={"primary_title": "Poll Comic"})
    assert r.status_code == 201

    next_poll = r.json()["next_poll_at"]
    assert next_poll is not None
    next_poll_dt = datetime.fromisoformat(next_poll)
    if next_poll_dt.tzinfo is None:
        next_poll_dt = next_poll_dt.replace(tzinfo=timezone.utc)
    assert next_poll_dt >= before + timedelta(days=6, hours=23)
    assert next_poll_dt <= before + timedelta(days=7, hours=1)


async def test_get_list_empty(logged_in_client):
    r = await logged_in_client.get("/api/requests")
    assert r.status_code == 200
    assert r.json() == []


async def test_get_list_returns_comic(logged_in_client):
    source = await _add_source()
    comic = await _add_comic(title="Listed Comic")
    await _add_assignment(comic.id, source.id, chapter_number=1.0)
    await _add_assignment(comic.id, source.id, chapter_number=2.0)

    r = await logged_in_client.get("/api/requests")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "Listed Comic"
    assert item["chapter_counts"]["total"] == 2
    assert item["chapter_counts"]["done"] == 2


async def test_get_detail_returns_chapters(logged_in_client):
    source = await _add_source()
    comic = await _add_comic(title="Detail Comic")
    await _add_assignment(comic.id, source.id, chapter_number=1.0)
    await _add_assignment(comic.id, source.id, chapter_number=2.0)

    r = await logged_in_client.get(f"/api/requests/{comic.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Detail Comic"
    assert len(data["chapters"]) == 2
    chapter_numbers = {ch["chapter_number"] for ch in data["chapters"]}
    assert chapter_numbers == {1.0, 2.0}


async def test_get_detail_not_found(logged_in_client):
    r = await logged_in_client.get("/api/requests/99999")
    assert r.status_code == 404


async def test_delete_removes_comic(logged_in_client, monkeypatch):
    from app import database
    from app.workers import scheduler

    monkeypatch.setattr(scheduler, "remove_comic_jobs", lambda comic_id: None)

    source = await _add_source()
    comic = await _add_comic(title="Delete Me")
    await _add_assignment(comic.id, source.id)

    r = await logged_in_client.delete(f"/api/requests/{comic.id}")
    assert r.status_code == 204

    async with database.AsyncSessionLocal() as db:
        assert await db.get(Comic, comic.id) is None
        result = await db.execute(
            select(ChapterAssignment).where(ChapterAssignment.comic_id == comic.id)
        )
        assert result.scalars().all() == []


async def test_delete_not_found(logged_in_client):
    r = await logged_in_client.delete("/api/requests/99999")
    assert r.status_code == 404


async def test_delete_calls_remove_jobs(logged_in_client, monkeypatch):
    from app.workers import scheduler

    removed_ids = []
    monkeypatch.setattr(scheduler, "remove_comic_jobs", lambda comic_id: removed_ids.append(comic_id))

    source = await _add_source()
    comic = await _add_comic(title="Remove Jobs Comic")

    r = await logged_in_client.delete(f"/api/requests/{comic.id}")
    assert r.status_code == 204
    assert comic.id in removed_ids


async def test_delete_removes_files(logged_in_client, monkeypatch, tmp_path):
    from app.workers import scheduler

    monkeypatch.setattr(scheduler, "remove_comic_jobs", lambda comic_id: None)

    cbz_file = tmp_path / "chapter.cbz"
    cbz_file.write_bytes(b"fake cbz content")

    source = await _add_source()
    comic = await _add_comic(title="File Delete Comic")
    await _add_assignment(comic.id, source.id, library_path=str(cbz_file))

    assert cbz_file.exists()
    r = await logged_in_client.delete(f"/api/requests/{comic.id}?delete_files=true")
    assert r.status_code == 204
    assert not cbz_file.exists()


async def test_requires_auth(auth_client):
    r = await auth_client.post("/api/requests", json={"primary_title": "No Auth"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Integration tests — require live Suwayomi
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_integration(logged_in_client, suwayomi_settings, test_manga_title, monkeypatch):
    """POST with a real manga title; verify 201 and assignments have chapter IDs."""
    from app import database
    from app.services.suwayomi import list_sources as _list_sources
    from app.workers import scheduler

    sources = await _list_sources()
    if not sources:
        pytest.skip("No sources on live Suwayomi instance")

    for i, s in enumerate(sources):
        await _add_source(name=s["name"], suwayomi_source_id=s["id"], priority=i + 1)
    monkeypatch.setattr(scheduler, "register_comic_jobs", lambda comic: None)

    r = await logged_in_client.post("/api/requests", json={"primary_title": test_manga_title})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == test_manga_title

    async with database.AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChapterAssignment).where(ChapterAssignment.comic_id == data["id"])
        )
        assignments = result.scalars().all()

    assert len(assignments) > 0
    for a in assignments:
        assert a.suwayomi_chapter_id is not None
        assert a.suwayomi_chapter_id != ""
