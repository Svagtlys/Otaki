import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models.chapter_assignment import ChapterAssignment, DownloadStatus
from ..models.comic import Comic, ComicStatus
from ..services import source_selector
from ..services import suwayomi

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()  # module-level singleton


async def start(db: AsyncSession) -> None:
    """Load all tracking comics and register poll jobs, then start the scheduler."""
    result = await db.execute(
        select(Comic).where(Comic.status == ComicStatus.tracking)
    )
    comics = result.scalars().all()
    for comic in comics:
        _register_poll_job(comic)
    if not scheduler.running:
        scheduler.start()


def register_comic_jobs(comic: Comic) -> None:
    """Public API for #13 to call after creating a new comic."""
    _register_poll_job(comic)


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
            logger.info(
                "_poll_comic: comic_id=%d status=complete — skipping", comic_id
            )
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
            ch_num: (source, manga_id)
            for ch_num, (source, manga_id) in chapter_map.items()
            if ch_num not in existing_numbers
        }

        if new_entries:
            # Group new chapters by (source_id, suwayomi_manga_id) to batch
            # fetch_chapters calls.
            groups: dict[tuple[int, str], list[float]] = {}
            for ch_num, (source, manga_id) in new_entries.items():
                key = (source.id, manga_id)
                groups.setdefault(key, []).append(ch_num)

            for (source_id, manga_id), ch_nums in groups.items():
                try:
                    fetched = await suwayomi.fetch_chapters(manga_id)
                except Exception as exc:
                    logger.warning(
                        "_poll_comic: fetch_chapters failed for manga_id=%s: %r",
                        manga_id,
                        exc,
                    )
                    continue

                fetched_by_num = {ch["chapter_number"]: ch for ch in fetched}
                chapter_ids_to_enqueue: list[str] = []

                for ch_num in ch_nums:
                    ch_data = fetched_by_num.get(ch_num)
                    if ch_data is None:
                        logger.warning(
                            "_poll_comic: chapter %.1f not found in fetch result for manga_id=%s",
                            ch_num,
                            manga_id,
                        )
                        continue

                    assignment = ChapterAssignment(
                        comic_id=comic_id,
                        chapter_number=ch_num,
                        volume_number=ch_data.get("volume_number"),
                        source_id=source_id,
                        suwayomi_manga_id=manga_id,
                        suwayomi_chapter_id=ch_data["suwayomi_chapter_id"],
                        download_status=DownloadStatus.queued,
                        is_active=True,
                        chapter_published_at=ch_data["chapter_published_at"],
                    )
                    db.add(assignment)
                    chapter_ids_to_enqueue.append(ch_data["suwayomi_chapter_id"])

                if chapter_ids_to_enqueue:
                    try:
                        await suwayomi.enqueue_downloads(chapter_ids_to_enqueue)
                    except Exception as exc:
                        logger.warning(
                            "_poll_comic: enqueue_downloads failed for manga_id=%s: %r",
                            manga_id,
                            exc,
                        )

        comic.next_poll_at = datetime.now(timezone.utc) + timedelta(days=7)
        _register_poll_job(comic)

        await db.commit()
