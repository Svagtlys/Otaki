import logging
from datetime import datetime, timedelta, timezone

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models.chapter_assignment import ChapterAssignment, DownloadStatus
from ..models.comic import Comic, ComicStatus
from ..services import cadence_inferrer, source_selector, suwayomi

logger = logging.getLogger(f"otaki.{__name__}")


scheduler = AsyncIOScheduler()  # module-level singleton


async def start(db: AsyncSession) -> None:
    """Load all tracking comics and register poll and upgrade jobs, then start the scheduler."""
    result = await db.execute(select(Comic).where(Comic.status == ComicStatus.tracking))
    comics = result.scalars().all()
    for comic in comics:
        _register_poll_job(comic)
        _register_upgrade_job(comic)
    if not scheduler.running:
        scheduler.start()


def register_comic_jobs(comic: Comic) -> None:
    """Register poll and upgrade jobs for a comic. Called after creation."""
    _register_poll_job(comic)
    _register_upgrade_job(comic)


def remove_comic_jobs(comic_id: int) -> None:
    """Remove all scheduled jobs for a comic. Called when a comic is deleted."""
    for job_id in (f"poll_{comic_id}", f"upgrade_{comic_id}"):
        try:
            scheduler.remove_job(job_id)
        except JobLookupError:
            pass


def _effective_poll_days(comic: Comic) -> float:
    """Return the effective poll interval in days for *comic*.

    Priority: poll_override_days > inferred_cadence_days > DEFAULT_POLL_DAYS.
    A null poll_override_days means the user has not set an override, so the
    inferred cadence (if available) is used instead of a hardcoded default.
    """
    from ..config import settings

    return comic.poll_override_days or comic.inferred_cadence_days or settings.DEFAULT_POLL_DAYS


def _effective_upgrade_days(comic: Comic) -> float:
    """Return the effective upgrade check interval in days for *comic*.

    Priority: upgrade_override_days > inferred_cadence_days > poll_override_days > DEFAULT_POLL_DAYS.
    """
    from ..config import settings

    return (
        comic.upgrade_override_days
        or comic.inferred_cadence_days
        or comic.poll_override_days
        or settings.DEFAULT_POLL_DAYS
    )


def _register_poll_job(comic: Comic) -> None:
    scheduler.add_job(
        func=_poll_comic,
        trigger="date",
        run_date=comic.next_poll_at or datetime.now(timezone.utc),
        id=f"poll_{comic.id}",
        args=[comic.id],
        replace_existing=True,
    )


async def _poll_comic(comic_id: int) -> None:
    async with AsyncSessionLocal() as db:
        comic = await db.get(Comic, comic_id)
        if comic is None:
            logger.warning("_poll_comic: comic_id=%d not found — skipping", comic_id)
            return
        if comic.status == ComicStatus.complete:
            logger.info("_poll_comic: comic_id=%d status=complete — skipping", comic_id)
            return

        chapter_map = await source_selector.build_chapter_source_map(comic, db)

        existing_result = await db.execute(
            select(ChapterAssignment.chapter_number).where(
                ChapterAssignment.comic_id == comic_id,
                ChapterAssignment.is_active.is_(True),
            )
        )
        existing_numbers = {row[0] for row in existing_result.all()}

        new_entries = {
            ch_num: (source, manga_id, ch_data)
            for ch_num, (source, manga_id, ch_data) in chapter_map.items()
            if ch_num not in existing_numbers
        }

        if new_entries:
            enqueue_by_manga: dict[str, list[str]] = {}
            for ch_num, (source, manga_id, ch_data) in new_entries.items():
                assignment = ChapterAssignment(
                    comic_id=comic_id,
                    chapter_number=ch_num,
                    volume_number=ch_data.get("volume_number"),
                    source_id=source.id,
                    suwayomi_manga_id=manga_id,
                    suwayomi_chapter_id=ch_data["suwayomi_chapter_id"],
                    download_status=DownloadStatus.queued,
                    is_active=True,
                    chapter_published_at=ch_data["chapter_published_at"],
                )
                db.add(assignment)
                enqueue_by_manga.setdefault(manga_id, []).append(
                    ch_data["suwayomi_chapter_id"]
                )

            for manga_id, chapter_ids in enqueue_by_manga.items():
                try:
                    await suwayomi.enqueue_downloads(chapter_ids)
                except Exception as exc:
                    logger.warning(
                        "_poll_comic: enqueue_downloads failed for manga_id=%s: %r",
                        manga_id,
                        exc,
                    )

        if new_entries:
            await db.commit()
            comic.inferred_cadence_days = await cadence_inferrer.infer_cadence(comic.id, db)

        comic.next_poll_at = datetime.now(timezone.utc) + timedelta(
            days=_effective_poll_days(comic)
        )
        _register_poll_job(comic)

        await db.commit()


def _register_upgrade_job(comic: Comic) -> None:
    scheduler.add_job(
        func=_upgrade_comic,
        trigger="date",
        run_date=comic.next_upgrade_check_at or datetime.now(timezone.utc),
        id=f"upgrade_{comic.id}",
        args=[comic.id],
        replace_existing=True,
    )


async def _upgrade_comic(comic_id: int) -> None:
    async with AsyncSessionLocal() as db:
        comic = await db.get(Comic, comic_id)
        if comic is None:
            logger.warning("_upgrade_comic: comic_id=%d not found — skipping", comic_id)
            return
        if comic.status == ComicStatus.complete:
            logger.info(
                "_upgrade_comic: comic_id=%d status=complete — skipping", comic_id
            )
            return

        candidates = await source_selector.find_upgrade_candidates(comic, db)

        enqueue_by_manga: dict[str, list[str]] = {}
        for assignment, candidate_source, manga_id, ch_data in candidates:
            upgrade = ChapterAssignment(
                comic_id=comic_id,
                chapter_number=assignment.chapter_number,
                volume_number=ch_data.get("volume_number"),
                source_id=candidate_source.id,
                suwayomi_manga_id=manga_id,
                suwayomi_chapter_id=ch_data["suwayomi_chapter_id"],
                download_status=DownloadStatus.queued,
                is_active=False,
                chapter_published_at=ch_data["chapter_published_at"],
            )
            db.add(upgrade)
            enqueue_by_manga.setdefault(manga_id, []).append(
                ch_data["suwayomi_chapter_id"]
            )

        for manga_id, chapter_ids in enqueue_by_manga.items():
            try:
                await suwayomi.enqueue_downloads(chapter_ids)
            except Exception as exc:
                logger.warning(
                    "_upgrade_comic: enqueue_downloads failed for manga_id=%s: %r",
                    manga_id,
                    exc,
                )

        now = datetime.now(timezone.utc)
        comic.last_upgrade_check_at = now
        comic.next_upgrade_check_at = now + timedelta(days=_effective_upgrade_days(comic))
        _register_upgrade_job(comic)

        await db.commit()
