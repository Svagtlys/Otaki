import pytest
from pathlib import Path

from app.models.comic import Comic, ComicStatus
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_comic(session, cover_path: str | None = None) -> Comic:
    comic = Comic(
        title="Test Comic",
        library_title="Test Comic",
        cover_path=cover_path,
        status=ComicStatus.tracking,
        poll_override_days=7,
        created_at=datetime.now(timezone.utc),
    )
    session.add(comic)
    await session.commit()
    await session.refresh(comic)
    return comic


# ---------------------------------------------------------------------------
# Cover endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cover_comic_not_found(logged_in_client):
    r = await logged_in_client.get("/api/requests/9999/cover")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_cover_no_cover_path_returns_404(logged_in_client_with_session):
    client, session = logged_in_client_with_session
    comic = await _create_comic(session, cover_path=None)
    r = await client.get(f"/api/requests/{comic.id}/cover")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_cover_returns_image(logged_in_client_with_session, tmp_path):
    client, session = logged_in_client_with_session
    cover_file = tmp_path / "1.jpg"
    cover_file.write_bytes(b"fake-image-data")
    comic = await _create_comic(session, cover_path=str(cover_file))
    r = await client.get(f"/api/requests/{comic.id}/cover")
    assert r.status_code == 200
    assert r.content == b"fake-image-data"


# ---------------------------------------------------------------------------
# save_from_url unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_from_url_downloads_and_saves(tmp_path, monkeypatch):
    from app.services import cover_handler
    from app.config import settings

    monkeypatch.setattr(settings, "COVERS_PATH", str(tmp_path))

    import httpx

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "image/jpeg"}
        content = b"fake-cover-bytes"

    class FakeClient:
        def __init__(self, **kwargs): pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    path = await cover_handler.save_from_url(42, "http://example.com/cover.jpg")
    assert path.exists()
    assert path.read_bytes() == b"fake-cover-bytes"
    assert path.parent == tmp_path
    assert path.stem == "42"


@pytest.mark.asyncio
async def test_save_from_url_skips_on_http_error(tmp_path, monkeypatch):
    from app.services import cover_handler
    from app.config import settings

    monkeypatch.setattr(settings, "COVERS_PATH", str(tmp_path))

    import httpx

    class FakeBadResponse:
        status_code = 404
        headers = {"content-type": "text/plain"}
        content = b""

    class FakeClient:
        def __init__(self, **kwargs): pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return FakeBadResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    path = await cover_handler.save_from_url(42, "http://example.com/cover.jpg")
    assert path is None
