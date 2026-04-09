"""Tests for GET /api/settings/export and POST /api/settings/import/* (issue #114)."""

import io
import json
import zipfile
from datetime import datetime, timezone

import pytest

from app.models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from app.models.comic import Comic, ComicStatus
from app.models.comic_alias import ComicAlias
from app.models.comic_source_pin import ComicSourcePin
from app.models.source import Source


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _add_source(*, name="Src", suwayomi_source_id="src-bk-1", priority=1) -> Source:
    from app import database
    async with database.AsyncSessionLocal() as db:
        s = Source(
            suwayomi_source_id=suwayomi_source_id,
            name=name,
            priority=priority,
            enabled=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


async def _add_comic(*, title="Test Comic", library_title=None) -> Comic:
    from app import database
    async with database.AsyncSessionLocal() as db:
        c = Comic(
            title=title,
            library_title=library_title or title,
            status=ComicStatus.tracking,
            created_at=datetime.now(timezone.utc),
            next_poll_at=datetime.now(timezone.utc),
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c


async def _add_assignment(
    comic_id: int,
    source_id: int,
    *,
    chapter_number: float = 1.0,
    is_active: bool = True,
    suwayomi_chapter_id: str | None = None,
) -> ChapterAssignment:
    from app import database
    async with database.AsyncSessionLocal() as db:
        a = ChapterAssignment(
            comic_id=comic_id,
            chapter_number=chapter_number,
            source_id=source_id,
            suwayomi_manga_id="m-bk-1",
            suwayomi_chapter_id=suwayomi_chapter_id or f"ch-bk-{chapter_number}",
            download_status=DownloadStatus.done,
            is_active=is_active,
            chapter_published_at=datetime.now(timezone.utc),
            relocation_status=RelocationStatus.done,
        )
        db.add(a)
        await db.commit()
        await db.refresh(a)
        return a


def _make_zip(backup: dict, covers: dict[str, bytes] | None = None) -> bytes:
    """Create a zip bytes from a backup dict and optional cover files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("backup.json", json.dumps(backup))
        for name, data in (covers or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_requires_auth(auth_client):
    r = await auth_client.get("/api/settings/export")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_export_otaki_returns_zip(logged_in_client):
    source = await _add_source(suwayomi_source_id="src-exp-1")
    comic = await _add_comic(title="Export Comic")
    await _add_assignment(comic.id, source.id)

    r = await logged_in_client.get("/api/settings/export?format=otaki")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers.get("content-disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "backup.json" in zf.namelist()
    backup = json.loads(zf.read("backup.json"))
    assert backup["version"] == 1
    assert any(s["suwayomi_source_id"] == "src-exp-1" for s in backup["sources"])
    assert any(c["title"] == "Export Comic" for c in backup["comics"])
    assert len(backup["chapter_assignments"]) >= 1


@pytest.mark.asyncio
async def test_export_json_returns_json(logged_in_client):
    r = await logged_in_client.get("/api/settings/export?format=json")
    assert r.status_code == 200
    assert "json" in r.headers["content-type"]
    data = r.json()
    assert "version" in data
    assert "sources" in data
    assert "comics" in data


@pytest.mark.asyncio
async def test_export_csv_returns_csv(logged_in_client):
    source = await _add_source(suwayomi_source_id="src-csv-1")
    comic = await _add_comic(title="CSV Comic")
    await _add_assignment(comic.id, source.id, chapter_number=1.0)

    r = await logged_in_client.get("/api/settings/export?format=csv")
    assert r.status_code == 200
    assert "csv" in r.headers["content-type"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("comic_title")
    assert any("CSV Comic" in line for line in lines[1:])


@pytest.mark.asyncio
async def test_export_active_only_by_default(logged_in_client):
    source = await _add_source(suwayomi_source_id="src-act-1")
    comic = await _add_comic(title="Active Only Comic")
    await _add_assignment(comic.id, source.id, chapter_number=1.0, is_active=True, suwayomi_chapter_id="ch-act-active")
    await _add_assignment(comic.id, source.id, chapter_number=1.0, is_active=False, suwayomi_chapter_id="ch-act-inactive")

    r = await logged_in_client.get("/api/settings/export?format=json")
    data = r.json()
    chapter_ids = [ch["suwayomi_chapter_id"] for ch in data["chapter_assignments"]]
    assert "ch-act-active" in chapter_ids
    assert "ch-act-inactive" not in chapter_ids


@pytest.mark.asyncio
async def test_export_include_all_assignments(logged_in_client):
    source = await _add_source(suwayomi_source_id="src-all-1")
    comic = await _add_comic(title="All Assignments Comic")
    await _add_assignment(comic.id, source.id, chapter_number=1.0, is_active=True, suwayomi_chapter_id="ch-all-active")
    await _add_assignment(comic.id, source.id, chapter_number=1.0, is_active=False, suwayomi_chapter_id="ch-all-inactive")

    r = await logged_in_client.get("/api/settings/export?format=json&include_all_assignments=true")
    data = r.json()
    chapter_ids = [ch["suwayomi_chapter_id"] for ch in data["chapter_assignments"]]
    assert "ch-all-active" in chapter_ids
    assert "ch-all-inactive" in chapter_ids


# ---------------------------------------------------------------------------
# Preview tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_requires_auth(auth_client):
    r = await auth_client.post("/api/settings/import/preview")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_preview_invalid_zip_returns_422(logged_in_client):
    r = await logged_in_client.post(
        "/api/settings/import/preview",
        files={"file": ("bad.zip", b"not a zip", "application/zip")},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_preview_returns_new_comics(logged_in_client):
    source = await _add_source(suwayomi_source_id="src-prev-new")
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-prev-new", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Brand New Comic", "library_title": "Brand New Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [
            {"comic_id": 1, "source_id": 1, "chapter_number": 1.0, "volume_number": None,
             "suwayomi_manga_id": "m1", "suwayomi_chapter_id": "ch-prev-1",
             "download_status": "done", "is_active": True,
             "chapter_published_at": datetime.now(timezone.utc).isoformat(),
             "downloaded_at": None, "library_path": None, "relocation_status": "done",
             "source_chapter_name": None, "source_manga_title": None, "retry_count": 0},
        ],
    }
    r = await logged_in_client.post(
        "/api/settings/import/preview",
        files={"file": ("backup.zip", _make_zip(backup), "application/zip")},
    )
    assert r.status_code == 200
    data = r.json()
    assert any(c["title"] == "Brand New Comic" for c in data["new_comics"])
    assert data["comic_conflicts"] == []
    assert data["new_comics"][0]["import_chapters"] == 1


@pytest.mark.asyncio
async def test_preview_returns_comic_conflict(logged_in_client):
    await _add_comic(title="Conflict Comic")
    backup = {
        "version": 1,
        "sources": [],
        "comics": [{"_id": 1, "title": "Conflict Comic", "library_title": "Conflict Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [],
    }
    r = await logged_in_client.post(
        "/api/settings/import/preview",
        files={"file": ("backup.zip", _make_zip(backup), "application/zip")},
    )
    assert r.status_code == 200
    data = r.json()
    assert any(c["title"] == "Conflict Comic" for c in data["comic_conflicts"])
    assert data["new_comics"] == []


@pytest.mark.asyncio
async def test_preview_source_conflict_detected(logged_in_client):
    await _add_source(suwayomi_source_id="src-sc-1", priority=1)
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-sc-1", "name": "Src", "priority": 3, "enabled": False}],
        "comics": [],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [],
    }
    r = await logged_in_client.post(
        "/api/settings/import/preview",
        files={"file": ("backup.zip", _make_zip(backup), "application/zip")},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["source_conflicts"]) == 1
    sc = data["source_conflicts"][0]
    assert sc["import_priority"] == 3
    assert sc["existing_priority"] == 1


# ---------------------------------------------------------------------------
# Apply tests
# ---------------------------------------------------------------------------


def _multipart_apply(file_bytes: bytes, src_res: list, comic_res: list):
    return {
        "file": ("backup.zip", file_bytes, "application/zip"),
    }, {
        "source_resolutions": json.dumps(src_res),
        "comic_resolutions": json.dumps(comic_res),
    }


@pytest.mark.asyncio
async def test_apply_requires_auth(auth_client):
    r = await auth_client.post("/api/settings/import/apply")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_apply_creates_new_comic(logged_in_client):
    from app import database
    from sqlalchemy import select

    source = await _add_source(suwayomi_source_id="src-apply-new")
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-apply-new", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Applied Comic", "library_title": "Applied Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [{"comic_id": 1, "title": "Alt Title"}],
        "comic_source_pins": [],
        "chapter_assignments": [
            {"comic_id": 1, "source_id": 1, "chapter_number": 1.0, "volume_number": None,
             "suwayomi_manga_id": "m-ap1", "suwayomi_chapter_id": "ch-ap1",
             "download_status": "done", "is_active": True,
             "chapter_published_at": datetime.now(timezone.utc).isoformat(),
             "downloaded_at": None, "library_path": None, "relocation_status": "done",
             "source_chapter_name": None, "source_manga_title": None, "retry_count": 0},
        ],
    }
    zdata = _make_zip(backup)
    comic_res = [{"backup_id": 1, "action": "create"}]
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps(comic_res)},
    )
    assert r.status_code == 200
    result = r.json()
    assert result["comics"] == 1
    assert result["chapters"] == 1

    async with database.AsyncSessionLocal() as db:
        c = (await db.execute(select(Comic).where(Comic.title == "Applied Comic"))).scalar_one_or_none()
        assert c is not None
        aliases = (await db.execute(select(ComicAlias).where(ComicAlias.comic_id == c.id))).scalars().all()
        assert any(a.title == "Alt Title" for a in aliases)


@pytest.mark.asyncio
async def test_apply_create_with_title_override(logged_in_client):
    from app import database
    from sqlalchemy import select

    await _add_source(suwayomi_source_id="src-rename-1")
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-rename-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Original Title", "library_title": "Original Title",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [],
    }
    zdata = _make_zip(backup)
    comic_res = [{"backup_id": 1, "action": "create", "title_override": "Renamed Title"}]
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps(comic_res)},
    )
    assert r.status_code == 200
    async with database.AsyncSessionLocal() as db:
        c = (await db.execute(select(Comic).where(Comic.title == "Renamed Title"))).scalar_one_or_none()
        assert c is not None


@pytest.mark.asyncio
async def test_apply_skip_comic(logged_in_client):
    from app import database
    from sqlalchemy import select

    await _add_source(suwayomi_source_id="src-skip-1")
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-skip-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Skipped Comic", "library_title": "Skipped Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [],
    }
    zdata = _make_zip(backup)
    comic_res = [{"backup_id": 1, "action": "skip"}]
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps(comic_res)},
    )
    assert r.status_code == 200
    assert r.json()["comics"] == 0
    async with database.AsyncSessionLocal() as db:
        c = (await db.execute(select(Comic).where(Comic.title == "Skipped Comic"))).scalar_one_or_none()
        assert c is None


@pytest.mark.asyncio
async def test_apply_merge_adds_aliases_and_pins(logged_in_client):
    from app import database
    from sqlalchemy import select

    source = await _add_source(suwayomi_source_id="src-merge-1")
    existing = await _add_comic(title="Merge Target")

    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-merge-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Merge Target", "library_title": "Merge Target",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [{"comic_id": 1, "title": "Merged Alias"}],
        "comic_source_pins": [{"comic_id": 1, "source_id": 1, "suwayomi_manga_id": "m-merge-1"}],
        "chapter_assignments": [
            {"comic_id": 1, "source_id": 1, "chapter_number": 5.0, "volume_number": None,
             "suwayomi_manga_id": "m-merge-1", "suwayomi_chapter_id": "ch-merge-5",
             "download_status": "done", "is_active": True,
             "chapter_published_at": datetime.now(timezone.utc).isoformat(),
             "downloaded_at": None, "library_path": None, "relocation_status": "done",
             "source_chapter_name": None, "source_manga_title": None, "retry_count": 0},
        ],
    }
    zdata = _make_zip(backup)
    comic_res = [{"backup_id": 1, "action": "merge", "target_id": existing.id}]
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps(comic_res)},
    )
    assert r.status_code == 200
    result = r.json()
    assert result["comics"] == 0  # no new comic created
    assert result["chapters"] == 1

    async with database.AsyncSessionLocal() as db:
        aliases = (await db.execute(select(ComicAlias).where(ComicAlias.comic_id == existing.id))).scalars().all()
        assert any(a.title == "Merged Alias" for a in aliases)
        pins = (await db.execute(select(ComicSourcePin).where(ComicSourcePin.comic_id == existing.id))).scalars().all()
        assert any(p.suwayomi_manga_id == "m-merge-1" for p in pins)


@pytest.mark.asyncio
async def test_apply_merge_skips_existing_assignments(logged_in_client):
    source = await _add_source(suwayomi_source_id="src-dup-1")
    existing = await _add_comic(title="Dup Comic")
    await _add_assignment(existing.id, source.id, chapter_number=1.0, suwayomi_chapter_id="ch-dup-1")

    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-dup-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Dup Comic", "library_title": "Dup Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [
            {"comic_id": 1, "source_id": 1, "chapter_number": 1.0, "volume_number": None,
             "suwayomi_manga_id": "m-dup-1", "suwayomi_chapter_id": "ch-dup-1",
             "download_status": "done", "is_active": True,
             "chapter_published_at": datetime.now(timezone.utc).isoformat(),
             "downloaded_at": None, "library_path": None, "relocation_status": "done",
             "source_chapter_name": None, "source_manga_title": None, "retry_count": 0},
        ],
    }
    zdata = _make_zip(backup)
    comic_res = [{"backup_id": 1, "action": "merge", "target_id": existing.id}]
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps(comic_res)},
    )
    assert r.status_code == 200
    result = r.json()
    assert result["chapters"] == 0
    assert result["skipped"] >= 1


@pytest.mark.asyncio
async def test_apply_source_overwrite(logged_in_client):
    from app import database
    from sqlalchemy import select

    await _add_source(suwayomi_source_id="src-ow-1", priority=1)
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-ow-1", "name": "Src", "priority": 5, "enabled": False}],
        "comics": [],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [],
    }
    zdata = _make_zip(backup)
    src_res = [{"backup_id": 1, "action": "overwrite"}]
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": json.dumps(src_res), "comic_resolutions": "[]"},
    )
    assert r.status_code == 200
    async with database.AsyncSessionLocal() as db:
        s = (await db.execute(select(Source).where(Source.suwayomi_source_id == "src-ow-1"))).scalar_one()
        assert s.priority == 5
        assert s.enabled is False


@pytest.mark.asyncio
async def test_apply_source_skip(logged_in_client):
    from app import database
    from sqlalchemy import select

    await _add_source(suwayomi_source_id="src-sk-1", priority=1)
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-sk-1", "name": "Src", "priority": 5, "enabled": False}],
        "comics": [],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [],
    }
    zdata = _make_zip(backup)
    src_res = [{"backup_id": 1, "action": "skip"}]
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": json.dumps(src_res), "comic_resolutions": "[]"},
    )
    assert r.status_code == 200
    async with database.AsyncSessionLocal() as db:
        s = (await db.execute(select(Source).where(Source.suwayomi_source_id == "src-sk-1"))).scalar_one()
        assert s.priority == 1  # unchanged


@pytest.mark.asyncio
async def test_apply_restores_cover(logged_in_client, tmp_path, monkeypatch):
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "COVERS_PATH", str(tmp_path / "covers"))

    await _add_source(suwayomi_source_id="src-cov-1")
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-cov-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Cover Comic", "library_title": "Cover Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": "covers/1.jpg"}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [],
    }
    fake_cover = b"\xff\xd8\xff\xe0fake-jpeg"
    zdata = _make_zip(backup, {"covers/1.jpg": fake_cover})
    comic_res = [{"backup_id": 1, "action": "create"}]
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps(comic_res)},
    )
    assert r.status_code == 200
    assert r.json()["covers"] == 1
    cover_files = list((tmp_path / "covers").iterdir())
    assert len(cover_files) == 1
    assert cover_files[0].read_bytes() == fake_cover


@pytest.mark.asyncio
async def test_apply_idempotent(logged_in_client):
    await _add_source(suwayomi_source_id="src-idem-1")
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-idem-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Idempotent Comic", "library_title": "Idempotent Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [
            {"comic_id": 1, "source_id": 1, "chapter_number": 1.0, "volume_number": None,
             "suwayomi_manga_id": "m-idem", "suwayomi_chapter_id": "ch-idem-1",
             "download_status": "done", "is_active": True,
             "chapter_published_at": datetime.now(timezone.utc).isoformat(),
             "downloaded_at": None, "library_path": None, "relocation_status": "done",
             "source_chapter_name": None, "source_manga_title": None, "retry_count": 0},
        ],
    }
    zdata = _make_zip(backup)
    comic_res = [{"backup_id": 1, "action": "create"}]

    # First import
    r1 = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps(comic_res)},
    )
    assert r1.status_code == 200
    first = r1.json()
    assert first["comics"] == 1
    assert first["chapters"] == 1

    # Get the created comic id for merge on second import
    from app import database
    from sqlalchemy import select
    async with database.AsyncSessionLocal() as db:
        c = (await db.execute(select(Comic).where(Comic.title == "Idempotent Comic"))).scalar_one()

    comic_res2 = [{"backup_id": 1, "action": "merge", "target_id": c.id}]
    r2 = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps(comic_res2)},
    )
    assert r2.status_code == 200
    second = r2.json()
    assert second["comics"] == 0
    assert second["chapters"] == 0
    assert second["skipped"] >= 1


@pytest.mark.asyncio
async def test_apply_returns_summary(logged_in_client):
    await _add_source(suwayomi_source_id="src-sum-1")
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-sum-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Summary Comic", "library_title": "Summary Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "chapter_assignments": [],
    }
    zdata = _make_zip(backup)
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps([{"backup_id": 1, "action": "create"}])},
    )
    assert r.status_code == 200
    result = r.json()
    assert "comics" in result
    assert "chapters" in result
    assert "covers" in result
    assert "skipped" in result


# ---------------------------------------------------------------------------
# Source overrides in backup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_includes_source_overrides(logged_in_client):
    """Exported backup.json contains comic_source_overrides."""
    from app import database
    from app.models.comic_source_override import ComicSourceOverride

    src = await _add_source(suwayomi_source_id="src-ov-exp-1", priority=1)
    comic = await _add_comic(title="Override Export Comic")
    async with database.AsyncSessionLocal() as db:
        db.add(ComicSourceOverride(comic_id=comic.id, source_id=src.id, priority_override=99))
        await db.commit()

    r = await logged_in_client.get("/api/settings/export?format=json")
    assert r.status_code == 200
    data = r.json()
    overrides = data.get("comic_source_overrides", [])
    assert any(o["priority_override"] == 99 for o in overrides)


@pytest.mark.asyncio
async def test_apply_restores_source_overrides(logged_in_client):
    """Importing a backup re-creates ComicSourceOverride rows."""
    from app import database
    from app.models.comic_source_override import ComicSourceOverride
    from sqlalchemy import select

    await _add_source(suwayomi_source_id="src-ov-imp-1", priority=1)
    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-ov-imp-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Override Import Comic", "library_title": "Override Import Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "comic_source_overrides": [{"comic_id": 1, "source_id": 1, "priority_override": 42}],
        "chapter_assignments": [],
    }
    zdata = _make_zip(backup)
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={"source_resolutions": "[]", "comic_resolutions": json.dumps([{"backup_id": 1, "action": "create"}])},
    )
    assert r.status_code == 200

    async with database.AsyncSessionLocal() as db:
        from app.models.comic import Comic as C
        c = (await db.execute(select(C).where(C.title == "Override Import Comic"))).scalar_one()
        rows = (await db.execute(
            select(ComicSourceOverride).where(ComicSourceOverride.comic_id == c.id)
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].priority_override == 42


@pytest.mark.asyncio
async def test_apply_skips_duplicate_source_overrides(logged_in_client):
    """Merging into an existing comic does not duplicate override rows."""
    from app import database
    from app.models.comic_source_override import ComicSourceOverride
    from sqlalchemy import select

    src = await _add_source(suwayomi_source_id="src-ov-dup-1", priority=1)
    comic = await _add_comic(title="Override Dup Comic")
    async with database.AsyncSessionLocal() as db:
        db.add(ComicSourceOverride(comic_id=comic.id, source_id=src.id, priority_override=5))
        await db.commit()

    backup = {
        "version": 1,
        "sources": [{"_id": 1, "suwayomi_source_id": "src-ov-dup-1", "name": "Src", "priority": 1, "enabled": True}],
        "comics": [{"_id": 1, "title": "Override Dup Comic", "library_title": "Override Dup Comic",
                    "status": "tracking", "poll_override_days": None, "upgrade_override_days": None,
                    "inferred_cadence_days": None, "created_at": None, "cover_file": None}],
        "comic_aliases": [],
        "comic_source_pins": [],
        "comic_source_overrides": [{"comic_id": 1, "source_id": 1, "priority_override": 99}],
        "chapter_assignments": [],
    }
    zdata = _make_zip(backup)
    r = await logged_in_client.post(
        "/api/settings/import/apply",
        files={"file": ("backup.zip", zdata, "application/zip")},
        data={
            "source_resolutions": "[]",
            "comic_resolutions": json.dumps([{"backup_id": 1, "action": "merge", "target_id": comic.id}]),
        },
    )
    assert r.status_code == 200

    async with database.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ComicSourceOverride).where(ComicSourceOverride.comic_id == comic.id)
        )).scalars().all()
    # Only the original row — import did not duplicate or overwrite
    assert len(rows) == 1
    assert rows[0].priority_override == 5
