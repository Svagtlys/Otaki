import pytest


@pytest.mark.asyncio
async def test_list_sources_empty(logged_in_client):
    r = await logged_in_client.get("/api/sources")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_sources_ordered_by_priority(logged_in_client):
    # Create two sources out of priority order
    await logged_in_client.post(
        "/api/setup/sources",
        json={
            "sources": [
                {"id": "src-b", "name": "MangaPlus", "lang": "en", "icon_url": ""},
                {"id": "src-a", "name": "MangaDex", "lang": "en", "icon_url": ""},
            ]
        },
    )
    r = await logged_in_client.get("/api/sources")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["name"] == "MangaPlus"
    assert data[0]["priority"] == 1
    assert data[1]["name"] == "MangaDex"
    assert data[1]["priority"] == 2


@pytest.mark.asyncio
async def test_list_sources_requires_auth(auth_client):
    r = await auth_client.get("/api/sources")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_patch_source_enabled(logged_in_client):
    await logged_in_client.post(
        "/api/setup/sources",
        json={"sources": [{"id": "src-1", "name": "MangaDex", "lang": "en", "icon_url": ""}]},
    )
    sources = (await logged_in_client.get("/api/sources")).json()
    source_id = sources[0]["id"]

    r = await logged_in_client.patch(f"/api/sources/{source_id}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_patch_source_priority(logged_in_client):
    await logged_in_client.post(
        "/api/setup/sources",
        json={"sources": [{"id": "src-1", "name": "MangaDex", "lang": "en", "icon_url": ""}]},
    )
    sources = (await logged_in_client.get("/api/sources")).json()
    source_id = sources[0]["id"]

    r = await logged_in_client.patch(f"/api/sources/{source_id}", json={"priority": 5})
    assert r.status_code == 200
    assert r.json()["priority"] == 5


@pytest.mark.asyncio
async def test_patch_source_not_found(logged_in_client):
    r = await logged_in_client.patch("/api/sources/9999", json={"enabled": False})
    assert r.status_code == 404
    assert r.json()["detail"] == "Source not found"


@pytest.mark.asyncio
async def test_patch_source_requires_auth(auth_client):
    r = await auth_client.patch("/api/sources/1", json={"enabled": False})
    assert r.status_code == 401
