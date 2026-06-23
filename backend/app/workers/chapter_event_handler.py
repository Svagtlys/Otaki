import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import write_session
from ..models.chapter_assignment import (
    ChapterAssignment,
    DownloadStatus,
    RelocationStatus,
)
from ..models.comic import Comic
from ..services import file_relocator, suwayomi
from . import scheduler as scheduler_module

logger = logging.getLogger(f"otaki.{__name__}")

_RETRY_BASE_SECONDS = 300  # 5 minutes
_RETRY_CAP_SECONDS = 86400  # 24 hours


async def handle(
    event_type: str,
    suwayomi_chapter_id: str,
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
) -> None:
    """Dispatch a download event from Suwayomi.

    FINISHED → run the post-download pipeline (relocate / upgrade-swap).
    ERROR    → increment retry_count and schedule a re-enqueue, or mark
               permanently failed once MAX_DOWNLOAD_RETRIES is exhausted.

    Does not drive scheduling — that is APScheduler's responsibility.

    Deferred to 1.4: quality_scanner, QualityScan row, image_processor
    """
    if event_type == "ERROR":
        await _handle_error(
            suwayomi_chapter_id, chapter_name, manga_title, source_display_name
        )
        return

    # FINISHED path
    async with write_session() as db:
        assignment = await db.scalar(
            select(ChapterAssignment)
            .where(ChapterAssignment.suwayomi_chapter_id == suwayomi_chapter_id)
            .options(selectinload(ChapterAssignment.source))
        )
        if assignment is None:
            logger.warning(
                "handle() called for unknown suwayomi_chapter_id=%s — ignoring",
                suwayomi_chapter_id,
            )
            return

        if assignment.download_status == DownloadStatus.done:
            logger.info(
                "handle: chapter_id=%s already processed — ignoring duplicate FINISHED event",
                suwayomi_chapter_id,
            )
            return

        assignment.download_status = DownloadStatus.done
        assignment.downloaded_at = datetime.now(UTC)

        comic = await db.execute(
            select(Comic)
            .where(Comic.id == assignment.comic_id)
            .options(selectinload(Comic.aliases))
        )
        comic = comic.scalar_one()

        # Check whether this is an upgrade download (an active assignment already
        # exists for the same comic + chapter from a prior, lower-priority source).
        existing_active = await db.scalar(
            select(ChapterAssignment)
            .where(
                ChapterAssignment.comic_id == assignment.comic_id,
                ChapterAssignment.chapter_number == assignment.chapter_number,
                ChapterAssignment.is_active.is_(True),
                ChapterAssignment.id != assignment.id,
            )
            .options(selectinload(ChapterAssignment.source))
        )

        try:
            if existing_active is None:
                # Regular first download — relocate and mark active.
                await file_relocator.relocate(
                    assignment,
                    comic,
                    db,
                    chapter_name=chapter_name,
                    source_display_name=source_display_name,
                )
                assignment.is_active = True
            else:
                # Upgrade download — priority-aware swap decision.
                # A working download from ANY source beats a failed one.
                existing_failed = (
                    existing_active.download_status == DownloadStatus.failed
                    or existing_active.relocation_status == RelocationStatus.failed
                )

                if existing_failed:
                    # Existing is broken — any working download wins.
                    should_swap = True
                else:
                    # Compare effective priorities (lower number = higher priority).
                    from ..services import source_selector

                    incoming_priority = await source_selector.effective_priority(
                        assignment.source, comic, db
                    )
                    existing_priority = await source_selector.effective_priority(
                        existing_active.source, comic, db
                    )
                    # Swap only if incoming is strictly better (lower priority number).
                    should_swap = incoming_priority < existing_priority

                if should_swap:
                    await file_relocator.replace_in_library(
                        existing_active,
                        assignment,
                        comic,
                        db,
                        chapter_name=chapter_name,
                        source_display_name=source_display_name,
                    )
                    existing_active.is_active = False
                    assignment.is_active = True
                else:
                    # Lower-priority source completed — mark done but keep inactive.
                    logger.info(
                        "handle: incoming from lower-priority source (priority=%d vs %d) "
                        "— marking done but keeping existing active",
                        assignment.source.priority,
                        existing_active.source.priority,
                    )
                    assignment.is_active = False
        except Exception:
            logger.exception(
                "handle: relocation raised for chapter_id=%s comic=%r chapter=%s — "
                "assignment left in download_status=done, relocation_status=%s",
                suwayomi_chapter_id,
                comic.title if comic else "unknown",
                chapter_name,
                assignment.relocation_status,
            )

        if assignment.relocation_status == RelocationStatus.failed:
            logger.warning(
                "handle: relocation failed for chapter_id=%s comic=%r chapter=%s "
                "(staging file not found or path error)",
                suwayomi_chapter_id,
                comic.title if comic else "unknown",
                chapter_name,
            )

        await db.commit()


async def _handle_error(
    suwayomi_chapter_id: str,
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
) -> None:
    async with write_session() as db:
        assignment = await db.scalar(
            select(ChapterAssignment).where(
                ChapterAssignment.suwayomi_chapter_id == suwayomi_chapter_id
            )
        )
        if assignment is None:
            logger.warning(
                "_handle_error() called for unknown suwayomi_chapter_id=%s — ignoring",
                suwayomi_chapter_id,
            )
            return

        assignment.download_status = DownloadStatus.failed
        assignment.retry_count = (assignment.retry_count or 0) + 1

        if assignment.retry_count > settings.MAX_DOWNLOAD_RETRIES:
            logger.error(
                "_handle_error: chapter_id=%s exhausted %d retries — permanently failed",
                suwayomi_chapter_id,
                settings.MAX_DOWNLOAD_RETRIES,
            )
            await db.commit()
            return

        delay_seconds = min(
            _RETRY_BASE_SECONDS * (2 ** (assignment.retry_count - 1)),
            _RETRY_CAP_SECONDS,
        )
        run_date = datetime.now(UTC) + timedelta(seconds=delay_seconds)

        logger.info(
            "_handle_error: chapter_id=%s retry %d/%d scheduled in %ds",
            suwayomi_chapter_id,
            assignment.retry_count,
            settings.MAX_DOWNLOAD_RETRIES,
            delay_seconds,
        )

        assignment_id = assignment.id
        retry_count = assignment.retry_count
        chapter_id_str = assignment.suwayomi_chapter_id
        await db.commit()

    scheduler_module.scheduler.add_job(
        func=_retry_download,
        trigger="date",
        run_date=run_date,
        id=f"retry_download_{assignment_id}_{retry_count}",
        args=[assignment_id, chapter_id_str],
        replace_existing=True,
    )


async def _retry_download(assignment_id: int, suwayomi_chapter_id: str) -> None:
    """Re-enqueue a failed chapter download. Scheduled by _handle_error."""
    async with write_session() as db:
        assignment = await db.get(ChapterAssignment, assignment_id)
        if assignment is None:
            logger.warning(
                "_retry_download: assignment_id=%d not found — skipping", assignment_id
            )
            return
        if assignment.download_status != DownloadStatus.failed:
            logger.info(
                "_retry_download: assignment_id=%d status=%s — skipping",
                assignment_id,
                assignment.download_status,
            )
            return

        assignment.download_status = DownloadStatus.queued
        await db.commit()

    try:
        await suwayomi.enqueue_downloads([suwayomi_chapter_id])
        logger.info(
            "_retry_download: enqueued chapter_id=%s for retry", suwayomi_chapter_id
        )
    except Exception as exc:
        logger.warning(
            "_retry_download: enqueue_downloads failed for chapter_id=%s: %r",
            suwayomi_chapter_id,
            exc,
        )
        async with write_session() as db:
            assignment = await db.get(ChapterAssignment, assignment_id)
            if assignment is not None:
                assignment.download_status = DownloadStatus.failed
                await db.commit()
