import asyncio
import base64
import json
import logging
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
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

logger = logging.getLogger(f"otaki.{__name__}")


class SearchResult(BaseModel):
    title: str
    cover_url: str | None  # absolute Suwayomi URL — submitted to POST /api/requests
    cover_display_url: (
        str | None
    )  # /api/search/thumbnail proxy URL — used by <img> tags
    synopsis: str | None
    source_id: int
    source_name: str
    url: str | None
    suwayomi_manga_id: str


class SourceError(BaseModel):
    source_name: str
    reason: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
    source_errors: list[SourceError]


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

    try:
        async with httpx.AsyncClient(verify=False) as client:
            resp = await client.get(url, headers=headers, timeout=15)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Thumbnail request timed out")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Thumbnail fetch failed")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Thumbnail fetch failed")

    content_type = resp.headers.get("content-type", "image/jpeg")
    return Response(content=resp.content, media_type=content_type)


@router.get("")
async def search(
    q: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> SearchResponse:
    result = await db.execute(
        select(Source).where(Source.enabled == True).order_by(Source.priority)  # noqa: E712
    )
    sources = result.scalars().all()

    async def _search_source(source: Source) -> tuple[list[SearchResult], str | None]:
        """Return (results, error_reason). error_reason is None on success."""
        try:
            raw = await suwayomi.search_source(source.suwayomi_source_id, q)
            items = []
            for r in raw:
                cover = _absolute_cover_url(r.get("cover_url"))
                items.append(
                    SearchResult(
                        title=r["title"],
                        cover_url=cover,
                        cover_display_url=_display_url(cover),
                        synopsis=r.get("synopsis"),
                        source_id=source.id,
                        source_name=source.name,
                        url=r.get("url"),
                        suwayomi_manga_id=r.get("manga_id", ""),
                    )
                )
            return items, None
        except Exception as e:
            reason = suwayomi.classify_error(e)
            logger.warning(
                "search failed for source %s (%s): %r", source.name, reason, e
            )
            return [], reason

    gathered = await asyncio.gather(*[_search_source(s) for s in sources])

    all_results: list[SearchResult] = []
    source_errors: list[SourceError] = []
    for source, (items, error_reason) in zip(sources, gathered):
        all_results.extend(items)
        if error_reason is not None:
            source_errors.append(
                SourceError(source_name=source.name, reason=error_reason)
            )

    return SearchResponse(results=all_results, source_errors=source_errors)


@router.get("/stream")
async def search_stream(
    q: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> StreamingResponse:
    """Stream search results per-source as SSE events.

    Fires one search per enabled source concurrently; emits a JSON SSE event as
    each source responds rather than waiting for all sources to finish.

    Event shapes:
      data: {"source_name": "...", "results": [...]}   # success
      data: {"source_name": "...", "error": "..."}      # source failure
      data: [DONE]                                       # all sources finished

    Auth: Bearer token via Authorization header (use fetch + ReadableStream,
    not EventSource, which cannot send custom headers).
    """
    result = await db.execute(
        select(Source).where(Source.enabled == True).order_by(Source.priority)  # noqa: E712
    )
    sources = result.scalars().all()

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def _fetch(source: Source) -> None:
            try:
                raw = await suwayomi.search_source(source.suwayomi_source_id, q)
                items = []
                for r in raw:
                    cover = _absolute_cover_url(r.get("cover_url"))
                    items.append(
                        SearchResult(
                            title=r["title"],
                            cover_url=cover,
                            cover_display_url=_display_url(cover),
                            synopsis=r.get("synopsis"),
                            source_id=source.id,
                            source_name=source.name,
                            url=r.get("url"),
                            suwayomi_manga_id=r.get("manga_id", ""),
                        ).model_dump()
                    )
                await queue.put({"source_name": source.name, "results": items})
            except Exception as e:
                reason = suwayomi.classify_error(e)
                logger.warning(
                    "search/stream failed for source %s (%s): %r", source.name, reason, e
                )
                await queue.put({"source_name": source.name, "error": reason})

        tasks = [asyncio.create_task(_fetch(s)) for s in sources]
        remaining = len(tasks)
        while remaining > 0:
            payload = await queue.get()
            yield f"data: {json.dumps(payload)}\n\n"
            remaining -= 1
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
