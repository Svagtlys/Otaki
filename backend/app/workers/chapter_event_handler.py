import logging
from datetime import UTC, datetime

from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..models.chapter_assignment import ChapterAssignment, DownloadStatus
from ..models.comic import Comic
from ..services import file_relocator

logger = logging.getLogger(__name__)


async def handle(
    suwayomi_chapter_id: str,
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
) -> None:
    """Run the post-download pipeline for a completed chapter.

    Called by the download listener on each FINISHED event. Does not drive
    scheduling — that is APScheduler's responsibility.

    chapter_name, manga_title, and source_display_name are passed through to
    file_relocator calls for logging and future use.

    Deferred to 1.1: comicinfo_writer, cover_injector
    Deferred to 1.4: quality_scanner, QualityScan row, image_processor
    """
    async with AsyncSessionLocal() as db:
        assignment = await db.scalar(
            select(ChapterAssignment).where(
                ChapterAssignment.suwayomi_chapter_id == suwayomi_chapter_id
            )
        )
        if assignment is None:
            logger.warning(
                "handle() called for unknown suwayomi_chapter_id=%s — ignoring",
                suwayomi_chapter_id,
            )
            return

        assignment.download_status = DownloadStatus.done
        assignment.downloaded_at = datetime.now(UTC)

        comic = await db.get(Comic, assignment.comic_id)

        # Check whether this is an upgrade download (an active assignment already
        # exists for the same comic + chapter from a prior, lower-priority source).
        existing_active = await db.scalar(
            select(ChapterAssignment).where(
                ChapterAssignment.comic_id == assignment.comic_id,
                ChapterAssignment.chapter_number == assignment.chapter_number,
                ChapterAssignment.is_active.is_(True),
                ChapterAssignment.id != assignment.id,
            )
        )

        if existing_active is None:
            # Regular first download — relocate and mark active.
            await file_relocator.relocate(
                assignment,
                comic,
                db,
                chapter_name=chapter_name,
                manga_title=manga_title,
                source_display_name=source_display_name,
            )
            assignment.is_active = True
        else:
            # Upgrade download — always swap for 1.0 (no quality condition until
            # quality_scanner is added in 1.4; a higher-priority source is
            # unconditionally better).
            await file_relocator.replace_in_library(
                existing_active,
                assignment,
                comic,
                db,
                chapter_name=chapter_name,
                manga_title=manga_title,
                source_display_name=source_display_name,
            )
            existing_active.is_active = False
            assignment.is_active = True

        await db.commit()
