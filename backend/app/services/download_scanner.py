"""Scan Suwayomi's download directory for CBZ files matching pending assignments.

Called at startup and on demand via POST /api/requests/scan-downloads.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from ..models.comic import Comic
from . import file_relocator

logger = logging.getLogger(f"otaki.{__name__}")


async def scan_existing_downloads(db: AsyncSession) -> dict:
    """Find staging files for pending assignments and run the relocate pipeline.

    Returns {"scanned": N, "found": N, "relocated": N, "failed": N}.
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
        except Exception:
            logger.exception(
                "scan_existing_downloads: relocation failed for assignment_id=%d "
                "comic=%r chapter=%s",
                assignment.id,
                comic.title,
                assignment.source_chapter_name,
            )
            failed += 1

    await db.commit()

    logger.info(
        "scan_existing_downloads: scanned=%d found=%d relocated=%d failed=%d",
        scanned, found, relocated, failed,
    )
    return {"scanned": scanned, "found": found, "relocated": relocated, "failed": failed}
