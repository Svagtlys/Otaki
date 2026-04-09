"""Scan Suwayomi's download directory for CBZ files matching pending assignments.

Called at startup and on demand via POST /api/requests/scan-downloads.
GET /api/requests/scan-downloads/all provides a full directory walk for discovery.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from ..models.comic import Comic
from ..models.comic_alias import ComicAlias
from . import file_relocator
from .file_relocator import _normalize_source_name, _title_regex

logger = logging.getLogger(f"otaki.{__name__}")


async def scan_existing_downloads(db: AsyncSession) -> dict:
    """Find staging files for pending assignments and run the relocate pipeline.

    Returns {
        "scanned": N, "found": N, "relocated": N, "failed": N,
        "results": [{"comic_title", "chapter_number", "source_name", "chapter_name", "status"}]
    }.
    """
    assignments = (
        await db.execute(
            select(ChapterAssignment)
            .where(
                ChapterAssignment.relocation_status != RelocationStatus.done,
                ChapterAssignment.source_chapter_name.is_not(None),
            )
            .options(selectinload(ChapterAssignment.source))
        )
    ).scalars().all()

    scanned = len(assignments)
    found = 0
    relocated = 0
    failed = 0
    results = []

    for assignment in assignments:
        source = assignment.source
        if source is None:
            continue

        staging = file_relocator.find_staging_path(
            assignment.source_chapter_name,
            assignment.source_manga_title or "",
            source.name,
        )
        if staging is None:
            continue

        found += 1

        if assignment.download_status != DownloadStatus.done:
            assignment.download_status = DownloadStatus.done
            assignment.downloaded_at = datetime.now(UTC)

        comic = await db.get(Comic, assignment.comic_id)
        if comic is None:
            logger.warning(
                "scan_existing_downloads: comic_id=%d not found for assignment %d — skipping",
                assignment.comic_id,
                assignment.id,
            )
            failed += 1
            results.append({
                "comic_title": None,
                "chapter_number": assignment.chapter_number,
                "source_name": source.name,
                "chapter_name": assignment.source_chapter_name,
                "status": "failed",
            })
            continue

        existing_active = await db.scalar(
            select(ChapterAssignment).where(
                ChapterAssignment.comic_id == assignment.comic_id,
                ChapterAssignment.chapter_number == assignment.chapter_number,
                ChapterAssignment.is_active.is_(True),
                ChapterAssignment.id != assignment.id,
            )
        )

        try:
            if existing_active is None:
                await file_relocator.relocate(
                    assignment,
                    comic,
                    db,
                    chapter_name=assignment.source_chapter_name,
                    manga_title=assignment.source_manga_title or "",
                    source_display_name=source.name,
                )
                assignment.is_active = True
            else:
                await file_relocator.replace_in_library(
                    existing_active,
                    assignment,
                    comic,
                    db,
                    chapter_name=assignment.source_chapter_name,
                    manga_title=assignment.source_manga_title or "",
                    source_display_name=source.name,
                )
                existing_active.is_active = False
                assignment.is_active = True
            relocated += 1
            results.append({
                "comic_title": comic.title,
                "chapter_number": assignment.chapter_number,
                "source_name": source.name,
                "chapter_name": assignment.source_chapter_name,
                "status": "relocated",
            })
        except Exception:
            logger.exception(
                "scan_existing_downloads: relocation failed for assignment_id=%d "
                "comic=%r chapter=%s",
                assignment.id,
                comic.title,
                assignment.source_chapter_name,
            )
            failed += 1
            results.append({
                "comic_title": comic.title,
                "chapter_number": assignment.chapter_number,
                "source_name": source.name,
                "chapter_name": assignment.source_chapter_name,
                "status": "failed",
            })

    await db.commit()

    logger.info(
        "scan_existing_downloads: scanned=%d found=%d relocated=%d failed=%d",
        scanned, found, relocated, failed,
    )
    return {
        "scanned": scanned,
        "found": found,
        "relocated": relocated,
        "failed": failed,
        "results": results,
    }


async def scan_all_downloads(db: AsyncSession) -> dict:
    """Walk SUWAYOMI_DOWNLOAD_PATH and classify every manga directory.

    No DB writes. Returns:
    {
        "matched": [{"source_name", "manga_dir", "comic_id", "comic_title", "chapter_count"}],
        "unmatched": [{"source_name", "manga_dir", "chapter_count"}]
    }
    """
    download_root = Path(settings.SUWAYOMI_DOWNLOAD_PATH) if settings.SUWAYOMI_DOWNLOAD_PATH else None
    if download_root is None or not download_root.exists():
        return {"matched": [], "unmatched": []}

    # Build title → comic lookup (lowercase, includes aliases)
    comics = (await db.execute(select(Comic))).scalars().all()
    aliases = (await db.execute(select(ComicAlias))).scalars().all()
    alias_map: dict[int, Comic] = {c.id: c for c in comics}

    # exact lowercase title → comic
    title_to_comic: dict[str, Comic] = {}
    for c in comics:
        title_to_comic[c.title.lower()] = c
        title_to_comic[c.library_title.lower()] = c
    for a in aliases:
        comic = alias_map.get(a.comic_id)
        if comic:
            title_to_comic[a.title.lower()] = comic

    # regex patterns: list of (pattern, comic) for fuzzy matching
    comic_patterns = [
        (_title_regex(c.title), c) for c in comics
    ] + [
        (_title_regex(c.library_title), c) for c in comics if c.library_title != c.title
    ] + [
        (_title_regex(a.title), alias_map[a.comic_id])
        for a in aliases if a.comic_id in alias_map
    ]

    def _match_comic(dir_name: str) -> Comic | None:
        lower = dir_name.lower()
        if lower in title_to_comic:
            return title_to_comic[lower]
        for pattern, comic in comic_patterns:
            if pattern.match(dir_name):
                return comic
        return None

    def _count_chapters(manga_dir: Path) -> int:
        return sum(
            1 for p in manga_dir.iterdir()
            if p.suffix == ".cbz" or p.is_dir()
        )

    matched = []
    unmatched = []

    for source_dir in sorted(download_root.iterdir()):
        if not source_dir.is_dir():
            continue
        for manga_dir in sorted(source_dir.iterdir()):
            if not manga_dir.is_dir():
                continue
            chapter_count = _count_chapters(manga_dir)
            comic = _match_comic(manga_dir.name)
            if comic is not None:
                matched.append({
                    "source_name": source_dir.name,
                    "manga_dir": manga_dir.name,
                    "comic_id": comic.id,
                    "comic_title": comic.title,
                    "chapter_count": chapter_count,
                })
            else:
                unmatched.append({
                    "source_name": source_dir.name,
                    "manga_dir": manga_dir.name,
                    "chapter_count": chapter_count,
                })

    logger.info(
        "scan_all_downloads: matched=%d unmatched=%d",
        len(matched), len(unmatched),
    )
    return {"matched": matched, "unmatched": unmatched}
