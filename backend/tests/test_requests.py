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

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))
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

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    r = await logged_in_client.post("/api/requests", json={"primary_title": "Another Manga"})
    assert r.status_code == 201
    assert r.json()["library_title"] == "Another Manga"


async def test_post_duplicate_title_returns_409(logged_in_client, monkeypatch):
    from app.services import source_selector, suwayomi

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))
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
        })}, []

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

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    registered = []
    monkeypatch.setattr(scheduler, "register_comic_jobs", lambda comic: registered.append(comic))

    r = await logged_in_client.post("/api/requests", json={"primary_title": "Job Comic"})
    assert r.status_code == 201
    assert len(registered) == 1
    assert registered[0].title == "Job Comic"


async def test_post_sets_next_poll_at(logged_in_client, monkeypatch):
    from app.services import source_selector, suwayomi

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))
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
# Cover endpoint tests
# ---------------------------------------------------------------------------


async def test_cover_post_url_saves_cover(logged_in_client, monkeypatch, tmp_path):
    from pathlib import Path as _Path
    from app.services import cover_handler

    fake_cover = tmp_path / "1.jpg"
    fake_cover.write_bytes(b"img")
    monkeypatch.setattr(cover_handler, "save_from_url", AsyncMock(return_value=fake_cover))

    comic = await _add_comic(title="Cover URL Comic")
    r = await logged_in_client.post(
        f"/api/requests/{comic.id}/cover",
        json={"url": "https://example.com/cover.jpg"},
    )
    assert r.status_code == 200
    assert r.json()["cover_url"] == f"/api/requests/{comic.id}/cover"


async def test_cover_post_url_502_on_failure(logged_in_client, monkeypatch):
    from app.services import cover_handler
    monkeypatch.setattr(cover_handler, "save_from_url", AsyncMock(return_value=None))

    comic = await _add_comic(title="Cover Fail Comic")
    r = await logged_in_client.post(
        f"/api/requests/{comic.id}/cover",
        json={"url": "https://example.com/cover.jpg"},
    )
    assert r.status_code == 502


async def test_cover_post_file_saves_cover(logged_in_client, monkeypatch, tmp_path):
    from app.services import cover_handler

    fake_cover = tmp_path / "1.jpg"
    fake_cover.write_bytes(b"img")
    monkeypatch.setattr(cover_handler, "save_from_file", MagicMock(return_value=fake_cover))

    comic = await _add_comic(title="Cover File Comic")
    r = await logged_in_client.post(
        f"/api/requests/{comic.id}/cover",
        files={"file": ("cover.jpg", b"img-data", "image/jpeg")},
    )
    assert r.status_code == 200
    assert "cover_url" in r.json()


async def test_cover_post_file_non_image_returns_415(logged_in_client, monkeypatch, tmp_path):
    from app.services import cover_handler
    monkeypatch.setattr(cover_handler, "save_from_file", MagicMock(return_value=None))

    comic = await _add_comic(title="Cover Non-Image Comic")
    r = await logged_in_client.post(
        f"/api/requests/{comic.id}/cover",
        files={"file": ("data.txt", b"not-an-image", "text/plain")},
    )
    assert r.status_code == 415


async def test_cover_post_404_for_unknown_comic(logged_in_client):
    r = await logged_in_client.post(
        "/api/requests/99999/cover",
        json={"url": "https://example.com/cover.jpg"},
    )
    assert r.status_code == 404


async def test_cover_delete_clears_cover_path(logged_in_client, tmp_path):
    from app import database

    fake_cover = tmp_path / "1.jpg"
    fake_cover.write_bytes(b"img")

    comic = await _add_comic(title="Cover Delete Comic")
    # Manually set cover_path
    async with database.AsyncSessionLocal() as db:
        c = await db.get(__import__("app.models.comic", fromlist=["Comic"]).Comic, comic.id)
        c.cover_path = str(fake_cover)
        await db.commit()

    r = await logged_in_client.delete(f"/api/requests/{comic.id}/cover")
    assert r.status_code == 204
    assert not fake_cover.exists()

    async with database.AsyncSessionLocal() as db:
        c = await db.get(__import__("app.models.comic", fromlist=["Comic"]).Comic, comic.id)
        assert c.cover_path is None


# ---------------------------------------------------------------------------
# requested_cover_url tests (#92)
# ---------------------------------------------------------------------------


async def test_create_request_stores_requested_cover_url(logged_in_client, monkeypatch):
    """cover_url submitted at request time is persisted as requested_cover_url."""
    from app import database
    from app.services import source_selector, cover_handler

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))
    # Cover download fails so requested_cover_url should remain set
    monkeypatch.setattr(cover_handler, "save_from_url", AsyncMock(return_value=None))

    r = await logged_in_client.post(
        "/api/requests",
        json={"primary_title": "Cover URL Stored", "cover_url": "https://example.com/cover.jpg"},
    )
    assert r.status_code == 201
    comic_id = r.json()["id"]

    async with database.AsyncSessionLocal() as db:
        comic = await db.get(Comic, comic_id)
    assert comic.requested_cover_url == "https://example.com/cover.jpg"
    assert comic.cover_path is None


async def test_create_request_clears_requested_cover_url_on_success(logged_in_client, monkeypatch, tmp_path):
    """requested_cover_url is nulled after a successful cover download at request time."""
    from app import database
    from app.services import source_selector, cover_handler

    fake_cover = tmp_path / "1.jpg"
    fake_cover.write_bytes(b"img")
    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))
    monkeypatch.setattr(cover_handler, "save_from_url", AsyncMock(return_value=fake_cover))

    r = await logged_in_client.post(
        "/api/requests",
        json={"primary_title": "Cover URL Cleared", "cover_url": "https://example.com/cover.jpg"},
    )
    assert r.status_code == 201
    comic_id = r.json()["id"]

    async with database.AsyncSessionLocal() as db:
        comic = await db.get(Comic, comic_id)
    assert comic.requested_cover_url is None
    assert comic.cover_path == str(fake_cover)


async def test_discover_retries_cover_when_missing(logged_in_client, monkeypatch, tmp_path):
    """discover_chapters downloads the cover if cover_path is None and requested_cover_url is set."""
    from app import database
    from app.services import source_selector, cover_handler

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))

    fake_cover = tmp_path / "1.jpg"
    fake_cover.write_bytes(b"img")
    save_mock = AsyncMock(return_value=fake_cover)
    monkeypatch.setattr(cover_handler, "save_from_url", save_mock)

    comic = await _add_comic(title="Discover Cover Comic")
    async with database.AsyncSessionLocal() as db:
        c = await db.get(Comic, comic.id)
        c.requested_cover_url = "https://example.com/cover.jpg"
        await db.commit()

    r = await logged_in_client.post(f"/api/requests/{comic.id}/discover")
    assert r.status_code == 200

    save_mock.assert_awaited_once_with(comic.id, "https://example.com/cover.jpg")

    async with database.AsyncSessionLocal() as db:
        c = await db.get(Comic, comic.id)
    assert c.cover_path == str(fake_cover)
    assert c.requested_cover_url is None


async def test_discover_does_not_overwrite_existing_cover(logged_in_client, monkeypatch, tmp_path):
    """discover_chapters skips the cover retry if cover_path is already set."""
    from app import database
    from app.services import source_selector, cover_handler

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))
    save_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(cover_handler, "save_from_url", save_mock)

    existing_cover = tmp_path / "existing.jpg"
    existing_cover.write_bytes(b"img")

    comic = await _add_comic(title="Discover No Overwrite Comic")
    async with database.AsyncSessionLocal() as db:
        c = await db.get(Comic, comic.id)
        c.cover_path = str(existing_cover)
        c.requested_cover_url = "https://example.com/new.jpg"
        await db.commit()

    r = await logged_in_client.post(f"/api/requests/{comic.id}/discover")
    assert r.status_code == 200

    save_mock.assert_not_awaited()

    async with database.AsyncSessionLocal() as db:
        c = await db.get(Comic, comic.id)
    assert c.cover_path == str(existing_cover)


# ---------------------------------------------------------------------------
# Integration tests — require live Suwayomi
# ---------------------------------------------------------------------------


async def test_discover_creates_missing_assignments(logged_in_client, monkeypatch):
    """POST /{id}/discover creates assignments for chapters not yet tracked."""
    from datetime import timezone
    from app import database
    from app.models.chapter_assignment import ChapterAssignment
    from app.services import source_selector, suwayomi
    from app.workers import scheduler

    # Set up a source and a comic with no assignments
    source = await _add_source(name="Src", suwayomi_source_id="src-disc", priority=1)
    comic = await _add_comic(title="Disc Comic")

    ch_data = {
        "chapter_number": 1.0,
        "volume_number": None,
        "suwayomi_chapter_id": "disc-ch-1",
        "chapter_published_at": datetime.now(timezone.utc),
    }
    monkeypatch.setattr(
        source_selector,
        "build_chapter_source_map",
        AsyncMock(return_value=({1.0: (source, "manga-disc", ch_data)}, [])),
    )
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())
    monkeypatch.setattr(scheduler, "register_comic_jobs", lambda c: None)

    r = await logged_in_client.post(f"/api/requests/{comic.id}/discover")
    assert r.status_code == 200
    assert r.json()["new_chapters"] == 1

    async with database.AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChapterAssignment).where(ChapterAssignment.comic_id == comic.id)
        )
        assignments = result.scalars().all()
    assert len(assignments) == 1
    assert assignments[0].suwayomi_chapter_id == "disc-ch-1"


async def test_discover_skips_existing_active_assignments(logged_in_client, monkeypatch):
    """POST /{id}/discover does not duplicate chapters already tracked with is_active=True."""
    from datetime import timezone
    from app import database
    from app.models.chapter_assignment import ChapterAssignment
    from app.services import source_selector, suwayomi
    from app.workers import scheduler

    source = await _add_source(name="Src2", suwayomi_source_id="src-disc2", priority=1)
    comic = await _add_comic(title="Disc Comic 2")
    await _add_assignment(comic.id, source.id, chapter_number=1.0)

    ch_data = {
        "chapter_number": 1.0,
        "volume_number": None,
        "suwayomi_chapter_id": "disc-ch-new",
        "chapter_published_at": datetime.now(timezone.utc),
    }
    monkeypatch.setattr(
        source_selector,
        "build_chapter_source_map",
        AsyncMock(return_value=({1.0: (source, "manga-disc2", ch_data)}, [])),
    )
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())
    monkeypatch.setattr(scheduler, "register_comic_jobs", lambda c: None)

    r = await logged_in_client.post(f"/api/requests/{comic.id}/discover")
    assert r.status_code == 200
    assert r.json()["new_chapters"] == 0

    async with database.AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChapterAssignment).where(ChapterAssignment.comic_id == comic.id)
        )
        assignments = result.scalars().all()
    assert len(assignments) == 1  # original only, no duplicate


async def test_discover_returns_404_for_unknown_comic(logged_in_client):
    r = await logged_in_client.post("/api/requests/99999/discover")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Alias tests (#96)
# ---------------------------------------------------------------------------


async def test_create_request_saves_aliases(logged_in_client, monkeypatch):
    """POST /api/requests with aliases saves ComicAlias rows in the DB."""
    from app import database
    from app.models.comic_alias import ComicAlias
    from app.services import source_selector

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))

    r = await logged_in_client.post(
        "/api/requests",
        json={
            "primary_title": "Alias Save Comic",
            "aliases": ["Alias One", "Alias Two"],
        },
    )
    assert r.status_code == 201
    comic_id = r.json()["id"]

    async with database.AsyncSessionLocal() as db:
        result = await db.execute(
            select(ComicAlias).where(ComicAlias.comic_id == comic_id)
        )
        aliases = result.scalars().all()

    alias_titles = {a.title for a in aliases}
    assert alias_titles == {"Alias One", "Alias Two"}


async def test_create_request_returns_aliases_in_response(logged_in_client, monkeypatch):
    """POST /api/requests response includes saved aliases."""
    from app.services import source_selector

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))

    r = await logged_in_client.post(
        "/api/requests",
        json={
            "primary_title": "Alias Response Comic",
            "aliases": ["Alt Title"],
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert "aliases" in data
    alias_titles = [a["title"] for a in data["aliases"]]
    assert "Alt Title" in alias_titles


async def test_get_detail_returns_aliases(logged_in_client, monkeypatch):
    """GET /{id} includes aliases in the response."""
    from app import database
    from app.models.comic_alias import ComicAlias
    from app.services import source_selector

    monkeypatch.setattr(source_selector, "build_chapter_source_map", AsyncMock(return_value=({}, [])))

    r = await logged_in_client.post(
        "/api/requests",
        json={"primary_title": "Detail Alias Comic", "aliases": ["Alt Name"]},
    )
    assert r.status_code == 201
    comic_id = r.json()["id"]

    r2 = await logged_in_client.get(f"/api/requests/{comic_id}")
    assert r2.status_code == 200
    data = r2.json()
    alias_titles = [a["title"] for a in data["aliases"]]
    assert "Alt Name" in alias_titles


async def test_add_alias_endpoint(logged_in_client):
    """POST /{id}/aliases creates a new alias."""
    from app import database
    from app.models.comic_alias import ComicAlias

    comic = await _add_comic(title="Alias Endpoint Comic")
    r = await logged_in_client.post(
        f"/api/requests/{comic.id}/aliases",
        json={"title": "New Alias"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "New Alias"
    assert "id" in data

    async with database.AsyncSessionLocal() as db:
        result = await db.execute(
            select(ComicAlias).where(ComicAlias.comic_id == comic.id)
        )
        aliases = result.scalars().all()
    assert any(a.title == "New Alias" for a in aliases)


async def test_add_alias_404_for_unknown_comic(logged_in_client):
    r = await logged_in_client.post(
        "/api/requests/99999/aliases",
        json={"title": "Ghost Alias"},
    )
    assert r.status_code == 404


async def test_delete_alias_endpoint(logged_in_client):
    """DELETE /{id}/aliases/{alias_id} removes the alias."""
    from app import database
    from app.models.comic_alias import ComicAlias

    comic = await _add_comic(title="Delete Alias Comic")
    async with database.AsyncSessionLocal() as db:
        alias = ComicAlias(comic_id=comic.id, title="To Delete")
        db.add(alias)
        await db.commit()
        await db.refresh(alias)

    r = await logged_in_client.delete(f"/api/requests/{comic.id}/aliases/{alias.id}")
    assert r.status_code == 204

    async with database.AsyncSessionLocal() as db:
        assert await db.get(ComicAlias, alias.id) is None


async def test_delete_alias_wrong_comic_returns_404(logged_in_client):
    """DELETE with alias_id belonging to a different comic returns 404."""
    from app import database
    from app.models.comic_alias import ComicAlias

    comic_a = await _add_comic(title="Comic A Alias")
    comic_b = await _add_comic(title="Comic B Alias")
    async with database.AsyncSessionLocal() as db:
        alias = ComicAlias(comic_id=comic_a.id, title="A's Alias")
        db.add(alias)
        await db.commit()
        await db.refresh(alias)

    r = await logged_in_client.delete(f"/api/requests/{comic_b.id}/aliases/{alias.id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH tests (#97)
# ---------------------------------------------------------------------------


async def test_patch_updates_library_title(logged_in_client):
    comic = await _add_comic(title="Patch Library Title Comic")
    r = await logged_in_client.patch(
        f"/api/requests/{comic.id}",
        json={"library_title": "New Library Name"},
    )
    assert r.status_code == 200
    assert r.json()["library_title"] == "New Library Name"

    from app import database
    async with database.AsyncSessionLocal() as db:
        c = await db.get(Comic, comic.id)
    assert c.library_title == "New Library Name"


async def test_patch_updates_poll_override_days_and_reschedules(logged_in_client, monkeypatch):
    from app.workers import scheduler

    registered = []
    monkeypatch.setattr(scheduler, "register_comic_jobs", lambda c: registered.append(c))

    comic = await _add_comic(title="Patch Poll Days Comic")
    r = await logged_in_client.patch(
        f"/api/requests/{comic.id}",
        json={"poll_override_days": 3.0},
    )
    assert r.status_code == 200
    assert r.json()["poll_override_days"] == 3.0
    assert len(registered) == 1
    assert registered[0].poll_override_days == 3.0


async def test_patch_clears_upgrade_override_days(logged_in_client, monkeypatch):
    from app import database
    from app.workers import scheduler

    monkeypatch.setattr(scheduler, "register_comic_jobs", lambda c: None)

    comic = await _add_comic(title="Patch Upgrade Clear Comic")
    async with database.AsyncSessionLocal() as db:
        c = await db.get(Comic, comic.id)
        c.upgrade_override_days = 14.0
        await db.commit()

    r = await logged_in_client.patch(
        f"/api/requests/{comic.id}",
        json={"upgrade_override_days": None},
    )
    assert r.status_code == 200
    assert r.json()["upgrade_override_days"] is None

    async with database.AsyncSessionLocal() as db:
        c = await db.get(Comic, comic.id)
    assert c.upgrade_override_days is None


async def test_patch_status_complete_removes_jobs(logged_in_client, monkeypatch):
    from app.workers import scheduler

    removed = []
    monkeypatch.setattr(scheduler, "remove_comic_jobs", lambda cid: removed.append(cid))

    comic = await _add_comic(title="Patch Status Complete Comic")
    r = await logged_in_client.patch(
        f"/api/requests/{comic.id}",
        json={"status": "complete"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "complete"
    assert comic.id in removed


async def test_patch_status_tracking_registers_jobs(logged_in_client, monkeypatch):
    from app import database
    from app.models.comic import ComicStatus
    from app.workers import scheduler

    registered = []
    monkeypatch.setattr(scheduler, "register_comic_jobs", lambda c: registered.append(c))

    comic = await _add_comic(title="Patch Status Tracking Comic")
    async with database.AsyncSessionLocal() as db:
        c = await db.get(Comic, comic.id)
        c.status = ComicStatus.complete
        await db.commit()

    r = await logged_in_client.patch(
        f"/api/requests/{comic.id}",
        json={"status": "tracking"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "tracking"
    assert len(registered) == 1


async def test_patch_empty_body_is_noop(logged_in_client):
    comic = await _add_comic(title="Patch Noop Comic")
    r = await logged_in_client.patch(f"/api/requests/{comic.id}", json={})
    assert r.status_code == 200
    assert r.json()["title"] == "Patch Noop Comic"


async def test_patch_not_found(logged_in_client):
    r = await logged_in_client.patch("/api/requests/99999", json={"library_title": "Ghost"})
    assert r.status_code == 404


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


# ---------------------------------------------------------------------------
# POST /{id}/reprocess tests
# ---------------------------------------------------------------------------


async def test_reprocess_404_for_unknown_comic(logged_in_client):
    r = await logged_in_client.post("/api/requests/99999/reprocess")
    assert r.status_code == 404


async def test_reprocess_returns_503_when_suwayomi_unreachable(logged_in_client, monkeypatch):
    """If list_sources() fails (Suwayomi unreachable), reprocess returns 503 JSON."""
    from app.services import suwayomi
    import httpx

    comic = await _add_comic(title="Reprocess 503 Comic")
    monkeypatch.setattr(
        suwayomi, "list_sources",
        AsyncMock(side_effect=httpx.TimeoutException("timed out")),
    )

    r = await logged_in_client.post(f"/api/requests/{comic.id}/reprocess")
    assert r.status_code == 503
    data = r.json()
    assert "detail" in data
    assert "unreachable" in data["detail"].lower()


async def test_reprocess_skips_queued_and_downloading(logged_in_client, monkeypatch, tmp_path):
    """Chapters already queued or downloading are counted as skipped."""
    from app import database
    from app.services import file_relocator, suwayomi

    source = await _add_source(name="Src", suwayomi_source_id="src-rp1", priority=1)
    comic = await _add_comic(title="Reprocess Comic 1")

    monkeypatch.setattr(suwayomi, "list_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(file_relocator, "find_staging_path", lambda *a, **kw: None)

    async with database.AsyncSessionLocal() as db:
        for status, ch_num in [(DownloadStatus.queued, 1.0), (DownloadStatus.downloading, 2.0)]:
            a = ChapterAssignment(
                comic_id=comic.id, chapter_number=ch_num, source_id=source.id,
                suwayomi_manga_id="m1", suwayomi_chapter_id=f"ch-{ch_num}",
                download_status=status, is_active=True,
                chapter_published_at=datetime.now(timezone.utc),
                relocation_status=RelocationStatus.pending,
            )
            db.add(a)
        await db.commit()

    r = await logged_in_client.post(f"/api/requests/{comic.id}/reprocess")
    assert r.status_code == 200
    data = r.json()
    assert data["skipped"] == 2
    assert data["queued"] == 0
    assert data["processed"] == 0


async def test_reprocess_reenqueues_failed(logged_in_client, monkeypatch, tmp_path):
    """Failed chapters are re-enqueued and counted as queued."""
    from app import database
    from app.services import file_relocator, suwayomi

    source = await _add_source(name="Src", suwayomi_source_id="src-rp2", priority=1)
    comic = await _add_comic(title="Reprocess Comic 2")

    monkeypatch.setattr(suwayomi, "list_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(file_relocator, "find_staging_path", lambda *a, **kw: None)
    monkeypatch.setattr(suwayomi, "enqueue_downloads", AsyncMock())

    async with database.AsyncSessionLocal() as db:
        a = ChapterAssignment(
            comic_id=comic.id, chapter_number=1.0, source_id=source.id,
            suwayomi_manga_id="m1", suwayomi_chapter_id="ch-fail",
            download_status=DownloadStatus.failed, is_active=True,
            chapter_published_at=datetime.now(timezone.utc),
            relocation_status=RelocationStatus.pending,
        )
        db.add(a)
        await db.commit()

    r = await logged_in_client.post(f"/api/requests/{comic.id}/reprocess")
    assert r.status_code == 200
    data = r.json()
    assert data["queued"] == 1
    assert data["processed"] == 0


async def test_reprocess_relocates_done_with_staging(logged_in_client, monkeypatch, tmp_path):
    """Chapters with download_status=done and a staging file are relocated."""
    from app import database
    from app.services import file_relocator, suwayomi

    source = await _add_source(name="Src", suwayomi_source_id="src-rp3", priority=1)
    comic = await _add_comic(title="Reprocess Comic 3")

    fake_staging = tmp_path / "fake.cbz"
    fake_staging.write_bytes(b"")

    monkeypatch.setattr(suwayomi, "list_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(file_relocator, "find_staging_path", lambda *a, **kw: fake_staging)
    mock_relocate = AsyncMock()
    monkeypatch.setattr(file_relocator, "relocate", mock_relocate)

    async with database.AsyncSessionLocal() as db:
        a = ChapterAssignment(
            comic_id=comic.id, chapter_number=1.0, source_id=source.id,
            suwayomi_manga_id="m1", suwayomi_chapter_id="ch-stg",
            download_status=DownloadStatus.done, is_active=True,
            chapter_published_at=datetime.now(timezone.utc),
            relocation_status=RelocationStatus.pending,
        )
        db.add(a)
        await db.commit()

    r = await logged_in_client.post(f"/api/requests/{comic.id}/reprocess")
    assert r.status_code == 200
    assert r.json()["processed"] == 1
    mock_relocate.assert_awaited_once()


async def test_reprocess_calls_update_library_file_for_done_chapters(
    logged_in_client, monkeypatch, tmp_path
):
    """Chapters with relocation_status=done and an existing library file call update_library_file."""
    from app import database
    from app.services import file_relocator, suwayomi

    source = await _add_source(name="Src", suwayomi_source_id="src-rp4", priority=1)
    comic = await _add_comic(title="Reprocess Comic 4")

    # Create an actual file so Path.exists() returns True
    lib_file = tmp_path / "library" / "ch1.cbz"
    lib_file.parent.mkdir(parents=True)
    lib_file.write_bytes(b"")

    monkeypatch.setattr(suwayomi, "list_sources", AsyncMock(return_value=[]))
    mock_update = AsyncMock()
    monkeypatch.setattr(file_relocator, "update_library_file", mock_update)

    async with database.AsyncSessionLocal() as db:
        a = ChapterAssignment(
            comic_id=comic.id, chapter_number=1.0, source_id=source.id,
            suwayomi_manga_id="m1", suwayomi_chapter_id="ch-lib",
            download_status=DownloadStatus.done, is_active=True,
            chapter_published_at=datetime.now(timezone.utc),
            library_path=str(lib_file),
            relocation_status=RelocationStatus.done,
        )
        db.add(a)
        await db.commit()

    r = await logged_in_client.post(f"/api/requests/{comic.id}/reprocess")
    assert r.status_code == 200
    assert r.json()["processed"] == 1
    mock_update.assert_awaited_once()
