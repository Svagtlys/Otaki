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


def _find_matching_result(results: list[dict], titles: list[str]) -> dict | None:
    """Return the first result whose title case-insensitively matches any entry in titles."""
    lower_titles = {t.lower() for t in titles}
    for result in results:
        if result.get("title", "").lower() in lower_titles:
            return result
    return None


async def effective_priority(source: Source, comic: Comic, db: AsyncSession) -> int:
    """Return the effective priority of a source for a given comic.

    Currently returns source.priority directly. Stubbed as async so callers
    need no changes when 1.3 adds ComicSourceOverride lookup.
    """
    return source.priority


async def build_chapter_source_map(
    comic: Comic,
    db: AsyncSession,
) -> tuple[dict[float, tuple[Source, str, dict]], list[dict]]:
    """Return the best source for each chapter available across all enabled sources.

    Returns (chapter_map, source_errors) where:
      chapter_map: {chapter_number: (best_source, suwayomi_manga_id, chapter_data)}
      source_errors: [{"source_name": str, "reason": str}] for sources that failed

    All three values per chapter are included so callers can create ChapterAssignment
    rows and enqueue downloads without any additional Suwayomi calls.

    Uses comic.title only — alias lookup is deferred to 1.1.
    Per-comic source priority overrides are deferred to 1.3.
    """
    result = await db.execute(
        select(Source).where(Source.enabled == True).order_by(Source.priority)
    )
    sources = result.scalars().all()

    async def _chapters_for_source(
        source: Source,
    ) -> tuple[list[tuple[Source, str, dict]], str | None]:
        """Return (chapters, error_reason). error_reason is None on success."""
        try:
            search_results = await suwayomi.search_source(
                source.suwayomi_source_id, comic.title
            )
            if not search_results:
                return [], None
            match = _find_matching_result(search_results, [comic.title])
            if match is None:
                logger.warning(
                    "source %s: no title match for %r — skipping", source.name, comic.title
                )
                return [], None
            manga_id = match["manga_id"]
            chapters = await suwayomi.fetch_chapters(manga_id)
            return [(source, manga_id, ch) for ch in chapters], None
        except Exception as e:
            reason = suwayomi.classify_error(e)
            logger.warning(
                "source %s failed during chapter fetch (%s): %r", source.name, reason, e
            )
            return [], reason

    gathered = await asyncio.gather(
        *[_chapters_for_source(s) for s in sources],
        return_exceptions=False,
    )

    # For each chapter number, keep the entry from the highest-priority source
    # (lowest effective_priority value).
    best: dict[float, tuple[int, Source, str, dict]] = {}  # chapter_number → (eff_priority, source, manga_id, ch_data)
    source_errors: list[dict] = []
    for source, (source_results, error_reason) in zip(sources, gathered):
        if error_reason is not None:
            source_errors.append({"source_name": source.name, "reason": error_reason})
        for src, manga_id, chapter in source_results:
            ch_num = chapter["chapter_number"]
            eff = await effective_priority(src, comic, db)
            if ch_num not in best or eff < best[ch_num][0]:
                best[ch_num] = (eff, src, manga_id, chapter)

    chapter_map = {ch_num: (src, manga_id, ch_data) for ch_num, (_, src, manga_id, ch_data) in best.items()}
    return chapter_map, source_errors


async def find_upgrade_candidates(
    comic: Comic,
    db: AsyncSession,
) -> list[tuple[ChapterAssignment, Source, str, dict]]:
    """Return (assignment, candidate_source, manga_id, chapter_data) tuples where
    a higher-priority source now has a chapter currently assigned to a lower-priority one.
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

    source_map, _ = await build_chapter_source_map(comic, db)

    candidates = []
    for assignment in assignments:
        entry = source_map.get(assignment.chapter_number)
        if entry is None:
            continue
        candidate_source, manga_id, ch_data = entry
        current_eff = await effective_priority(assignment.source, comic, db)
        candidate_eff = await effective_priority(candidate_source, comic, db)
        if candidate_eff < current_eff:
            candidates.append((assignment, candidate_source, manga_id, ch_data))

    return candidates
