import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.chapter_assignment import ChapterAssignment
from ..models.comic import Comic
from ..models.source import Source
from . import suwayomi

logger = logging.getLogger(__name__)


async def effective_priority(source: Source, comic: Comic, db: AsyncSession) -> int:
    """Return the effective priority of a source for a given comic.

    Currently returns source.priority directly. Stubbed as async so callers
    need no changes when 1.3 adds ComicSourceOverride lookup.
    """
    return source.priority


async def build_chapter_source_map(
    comic: Comic,
    db: AsyncSession,
) -> dict[float, tuple[Source, str]]:
    """Return the best source for each chapter available across all enabled sources.

    Returns {chapter_number: (best_source, suwayomi_manga_id)}.
    The manga ID is included so callers can create ChapterAssignment rows
    without a second Suwayomi lookup.

    Uses comic.title only — alias lookup is deferred to 1.1.
    Per-comic source priority overrides are deferred to 1.3.
    """
    result = await db.execute(
        select(Source).where(Source.enabled == True).order_by(Source.priority)
    )
    sources = result.scalars().all()

    async def _chapters_for_source(
        source: Source,
    ) -> list[tuple[Source, str, dict]]:
        try:
            search_results = await suwayomi.search_source(
                source.suwayomi_source_id, comic.title
            )
            if not search_results:
                return []
            manga_id = search_results[0]["manga_id"]
            chapters = await suwayomi.fetch_chapters(manga_id)
            return [(source, manga_id, ch) for ch in chapters]
        except Exception as e:
            logger.warning(
                "source %s failed during chapter fetch: %r", source.name, e
            )
            return []

    gathered = await asyncio.gather(
        *[_chapters_for_source(s) for s in sources],
        return_exceptions=False,
    )

    # For each chapter number, keep the entry from the highest-priority source
    # (lowest effective_priority value).
    best: dict[float, tuple[int, Source, str]] = {}  # chapter_number → (eff_priority, source, manga_id)
    for source_results in gathered:
        for source, manga_id, chapter in source_results:
            ch_num = chapter["chapter_number"]
            eff = await effective_priority(source, comic, db)
            if ch_num not in best or eff < best[ch_num][0]:
                best[ch_num] = (eff, source, manga_id)

    return {ch_num: (source, manga_id) for ch_num, (_, source, manga_id) in best.items()}


async def find_upgrade_candidates(
    comic: Comic,
    db: AsyncSession,
) -> list[tuple[ChapterAssignment, Source]]:
    """Return (assignment, candidate_source) pairs where a higher-priority
    source now has a chapter that is currently assigned to a lower-priority one.
    """
    result = await db.execute(
        select(ChapterAssignment)
        .where(
            ChapterAssignment.comic_id == comic.id,
            ChapterAssignment.is_active == True,
        )
        .options(selectinload(ChapterAssignment.source))
    )
    assignments = result.scalars().all()
    if not assignments:
        return []

    source_map = await build_chapter_source_map(comic, db)

    candidates = []
    for assignment in assignments:
        entry = source_map.get(assignment.chapter_number)
        if entry is None:
            continue
        candidate_source, _ = entry
        current_eff = await effective_priority(assignment.source, comic, db)
        candidate_eff = await effective_priority(candidate_source, comic, db)
        if candidate_eff < current_eff:
            candidates.append((assignment, candidate_source))

    return candidates
