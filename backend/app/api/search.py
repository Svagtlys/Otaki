import asyncio
import base64
import logging
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.source import Source
from ..models.user import User
from ..services import suwayomi
from .auth import require_auth

router = APIRouter(prefix="/search", tags=["search"])

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    title: str
    cover_url: str | None       # absolute Suwayomi URL — submitted to POST /api/requests
    cover_display_url: str | None  # /api/search/thumbnail proxy URL — used by <img> tags
    synopsis: str | None
    source_id: int
    source_name: str
    url: str | None


def _absolute_cover_url(raw: str | None) -> str | None:
    """Convert a relative Suwayomi thumbnail path to an absolute URL."""
    if not raw:
        return None
    if raw.startswith("/") and settings.SUWAYOMI_URL:
        return f"{settings.SUWAYOMI_URL}{raw}"
    return raw


def _display_url(absolute: str | None) -> str | None:
    """Rewrite an absolute Suwayomi URL to go through our proxy endpoint."""
    if not absolute:
        return None
    return f"/api/search/thumbnail?url={urllib.parse.quote(absolute, safe='')}"


@router.get("/thumbnail")
async def thumbnail_proxy(
    url: str = Query(),
) -> Response:
    """Proxy a Suwayomi thumbnail, adding Basic auth credentials server-side.

    No auth required — <img> tags cannot send JWT tokens. The URL is validated
    to start with SUWAYOMI_URL so this cannot be used as an open proxy.
    """
    if not settings.SUWAYOMI_URL or not url.startswith(settings.SUWAYOMI_URL):
        raise HTTPException(status_code=400, detail="URL not allowed")

    headers: dict[str, str] = {}
    if settings.SUWAYOMI_USERNAME and settings.SUWAYOMI_PASSWORD:
        token = base64.b64encode(
            f"{settings.SUWAYOMI_USERNAME}:{settings.SUWAYOMI_PASSWORD}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {token}"

    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(url, headers=headers, timeout=15)

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Thumbnail fetch failed")

    content_type = resp.headers.get("content-type", "image/jpeg")
    return Response(content=resp.content, media_type=content_type)


@router.get("")
async def search(
    q: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> list[SearchResult]:
    result = await db.execute(
        select(Source).where(Source.enabled == True).order_by(Source.priority)  # noqa: E712
    )
    sources = result.scalars().all()

    async def _search_source(source: Source) -> list[SearchResult]:
        try:
            results = await suwayomi.search_source(source.suwayomi_source_id, q)
            items = []
            for r in results:
                cover = _absolute_cover_url(r.get("cover_url"))
                items.append(SearchResult(
                    title=r["title"],
                    cover_url=cover,
                    cover_display_url=_display_url(cover),
                    synopsis=r.get("synopsis"),
                    source_id=source.id,
                    source_name=source.name,
                    url=r.get("url"),
                ))
            return items
        except Exception as e:
            logger.warning("search failed for source %s: %r", source.name, e)
            return []

    gathered = await asyncio.gather(*[_search_source(s) for s in sources])
    return [item for source_results in gathered for item in source_results]
