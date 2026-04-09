"""Tests for comic-local source priority overrides (issue #112)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.comic import Comic, ComicStatus
from app.models.comic_source_override import ComicSourceOverride
from app.models.source import Source


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _add_source(*, name="Src", suwayomi_source_id="src-ov-1", priority=1, enabled=True) -> Source:
    from app import database
    async with database.AsyncSessionLocal() as db:
        s = Source(
            suwayomi_source_id=suwayomi_source_id,
            name=name,
            priority=priority,
            enabled=enabled,
            created_at=datetime.now(timezone.utc),
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


async def _add_comic(*, title="Test Comic") -> Comic:
    from app import database
    async with database.AsyncSessionLocal() as db:
        c = Comic(
            title=title,
            library_title=title,
            status=ComicStatus.tracking,
            created_at=datetime.now(timezone.utc),
            next_poll_at=datetime.now(timezone.utc),
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_overrides_requires_auth(auth_client):
    r = await auth_client.get("/api/requests/1/source-overrides")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_put_overrides_requires_auth(auth_client):
    r = await auth_client.put("/api/requests/1/source-overrides", json={"source_ids": []})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_overrides_requires_auth(auth_client):
    r = await auth_client.delete("/api/requests/1/source-overrides")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_overrides_empty(logged_in_client):
    src = await _add_source(suwayomi_source_id="src-list-1", priority=1)
    comic = await _add_comic(title="List Override Comic")

    r = await logged_in_client.get(f"/api/requests/{comic.id}/source-overrides")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    entry = next((e for e in data if e["source_id"] == src.id), None)
    assert entry is not None
    assert entry["is_overridden"] is False
    assert entry["effective_priority"] == entry["global_priority"]


@pytest.mark.asyncio
async def test_list_overrides_reflects_overrides(logged_in_client):
    src_a = await _add_source(suwayomi_source_id="src-refl-a", priority=1, name="Alpha")
    src_b = await _add_source(suwayomi_source_id="src-refl-b", priority=2, name="Beta")
    comic = await _add_comic(title="Reflect Override Comic")

    # Set B first, A second
    r = await logged_in_client.put(
        f"/api/requests/{comic.id}/source-overrides",
        json={"source_ids": [src_b.id, src_a.id]},
    )
    assert r.status_code == 200

    r = await logged_in_client.get(f"/api/requests/{comic.id}/source-overrides")
    data = r.json()
    eff = {e["source_id"]: e["effective_priority"] for e in data}
    assert eff[src_b.id] == 1
    assert eff[src_a.id] == 2
    assert all(e["is_overridden"] for e in data if e["source_id"] in (src_a.id, src_b.id))


@pytest.mark.asyncio
async def test_list_overrides_sorted_by_effective_priority(logged_in_client):
    src_a = await _add_source(suwayomi_source_id="src-sort-a", priority=1, name="A")
    src_b = await _add_source(suwayomi_source_id="src-sort-b", priority=2, name="B")
    comic = await _add_comic(title="Sort Override Comic")

    await logged_in_client.put(
        f"/api/requests/{comic.id}/source-overrides",
        json={"source_ids": [src_b.id, src_a.id]},
    )

    r = await logged_in_client.get(f"/api/requests/{comic.id}/source-overrides")
    data = r.json()
    priorities = [e["effective_priority"] for e in data if e["source_id"] in (src_a.id, src_b.id)]
    assert priorities == sorted(priorities)


@pytest.mark.asyncio
async def test_list_overrides_404_unknown_comic(logged_in_client):
    r = await logged_in_client.get("/api/requests/99999/source-overrides")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_creates_overrides(logged_in_client):
    from app import database

    src_a = await _add_source(suwayomi_source_id="src-put-a", priority=1, name="A")
    src_b = await _add_source(suwayomi_source_id="src-put-b", priority=2, name="B")
    comic = await _add_comic(title="Put Override Comic")

    r = await logged_in_client.put(
        f"/api/requests/{comic.id}/source-overrides",
        json={"source_ids": [src_b.id, src_a.id]},
    )
    assert r.status_code == 200
    data = r.json()
    eff = {e["source_id"]: e["effective_priority"] for e in data}
    assert eff[src_b.id] == 1
    assert eff[src_a.id] == 2

    async with database.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ComicSourceOverride).where(ComicSourceOverride.comic_id == comic.id)
        )).scalars().all()
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_put_replaces_existing_overrides(logged_in_client):
    src_a = await _add_source(suwayomi_source_id="src-rep-a", priority=1, name="A")
    src_b = await _add_source(suwayomi_source_id="src-rep-b", priority=2, name="B")
    comic = await _add_comic(title="Replace Override Comic")

    await logged_in_client.put(
        f"/api/requests/{comic.id}/source-overrides",
        json={"source_ids": [src_b.id, src_a.id]},
    )
    # Now reverse again
    r = await logged_in_client.put(
        f"/api/requests/{comic.id}/source-overrides",
        json={"source_ids": [src_a.id, src_b.id]},
    )
    assert r.status_code == 200
    eff = {e["source_id"]: e["effective_priority"] for e in r.json()}
    assert eff[src_a.id] == 1
    assert eff[src_b.id] == 2


@pytest.mark.asyncio
async def test_put_rejects_incomplete_list(logged_in_client):
    src_a = await _add_source(suwayomi_source_id="src-inc-a", priority=1)
    await _add_source(suwayomi_source_id="src-inc-b", priority=2)
    comic = await _add_comic(title="Incomplete Override Comic")

    # Only submit one of two enabled sources
    r = await logged_in_client.put(
        f"/api/requests/{comic.id}/source-overrides",
        json={"source_ids": [src_a.id]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_rejects_unknown_source(logged_in_client):
    await _add_source(suwayomi_source_id="src-unk-a", priority=1)
    comic = await _add_comic(title="Unknown Source Override Comic")

    r = await logged_in_client.put(
        f"/api/requests/{comic.id}/source-overrides",
        json={"source_ids": [99999]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_404_unknown_comic(logged_in_client):
    src = await _add_source(suwayomi_source_id="src-404-put")
    r = await logged_in_client.put(
        "/api/requests/99999/source-overrides",
        json={"source_ids": [src.id]},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_overrides(logged_in_client):
    from app import database

    src_a = await _add_source(suwayomi_source_id="src-del-a", priority=1)
    src_b = await _add_source(suwayomi_source_id="src-del-b", priority=2)
    comic = await _add_comic(title="Delete Override Comic")

    await logged_in_client.put(
        f"/api/requests/{comic.id}/source-overrides",
        json={"source_ids": [src_b.id, src_a.id]},
    )

    r = await logged_in_client.delete(f"/api/requests/{comic.id}/source-overrides")
    assert r.status_code == 204

    async with database.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ComicSourceOverride).where(ComicSourceOverride.comic_id == comic.id)
        )).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_delete_is_idempotent(logged_in_client):
    comic = await _add_comic(title="Delete Idempotent Comic")
    r = await logged_in_client.delete(f"/api/requests/{comic.id}/source-overrides")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_404_unknown_comic(logged_in_client):
    r = await logged_in_client.delete("/api/requests/99999/source-overrides")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# effective_priority (service unit tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_priority_falls_back_to_global(db_session):
    from app.services.source_selector import effective_priority

    src = Source(
        suwayomi_source_id="src-ep-global",
        name="Global Src",
        priority=3,
        enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    comic = Comic(
        title="EP Global Comic",
        library_title="EP Global Comic",
        status=ComicStatus.tracking,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(src)
    db_session.add(comic)
    await db_session.flush()

    result = await effective_priority(src, comic, db_session)
    assert result == 3


@pytest.mark.asyncio
async def test_effective_priority_uses_override(db_session):
    from app.services.source_selector import effective_priority

    src = Source(
        suwayomi_source_id="src-ep-override",
        name="Override Src",
        priority=3,
        enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    comic = Comic(
        title="EP Override Comic",
        library_title="EP Override Comic",
        status=ComicStatus.tracking,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(src)
    db_session.add(comic)
    await db_session.flush()

    override = ComicSourceOverride(
        comic_id=comic.id,
        source_id=src.id,
        priority_override=1,
    )
    db_session.add(override)
    await db_session.flush()

    result = await effective_priority(src, comic, db_session)
    assert result == 1
