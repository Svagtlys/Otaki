import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.source import Source
from ..services import suwayomi

router = APIRouter(prefix="/search", tags=["search"])

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    title: str
    cover_url: str | None
    synopsis: str | None
    source_id: int
    source_name: str
    url: str | None


@router.get("")
async def search(
    q: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
) -> list[SearchResult]:
    result = await db.execute(
        select(Source).where(Source.enabled == True).order_by(Source.priority)  # noqa: E712
    )
    sources = result.scalars().all()

    async def _search_source(source: Source) -> list[SearchResult]:
        try:
            results = await suwayomi.search_source(source.suwayomi_source_id, q)
            return [
                SearchResult(
                    title=r["title"],
                    cover_url=r.get("cover_url"),
                    synopsis=r.get("synopsis"),
                    source_id=source.id,
                    source_name=source.name,
                    url=r.get("url"),
                )
                for r in results
            ]
        except Exception as e:
            logger.warning("search failed for source %s: %r", source.name, e)
            return []

    gathered = await asyncio.gather(*[_search_source(s) for s in sources])
    return [item for source_results in gathered for item in source_results]
