import asyncio
import logging

from gql.transport.exceptions import TransportError

from ..config import settings
from ..services import suwayomi
from . import chapter_event_handler

logger = logging.getLogger(f"otaki.{__name__}")

_background_tasks: set[asyncio.Task] = set()
# chapter_id → poll item dict from the most recent poll snapshot
_polled_items: dict[str, dict] = {}
# chapter_ids where an ERROR event has already been dispatched in polling mode
_emitted_error_ids: set[str] = set()


def _dispatch(
    event_type: str,
    chapter_id: str,
    chapter_name: str,
    manga_title: str,
    source_name: str,
) -> None:
    """Schedule chapter_event_handler.handle() as a background task."""
    task = asyncio.create_task(
        chapter_event_handler.handle(
            event_type, chapter_id, chapter_name, manga_title, source_name
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _process_poll_result(items: list[dict]) -> None:
    """Infer FINISHED/ERROR events from a poll snapshot and dispatch them.

    Suwayomi removes completed downloads from the queue immediately, so an item
    that was present in the previous snapshot and is absent now is assumed to have
    finished successfully.

    - Items that disappeared and were not previously dispatched as ERROR → FINISHED.
    - Items still in the queue with state ERROR that have not been dispatched → ERROR
      (tracked in ``_emitted_error_ids`` to avoid duplicates).
    """
    global _polled_items, _emitted_error_ids

    current = {item["chapter_id"]: item for item in items}

    # Items that were in the queue and are now gone → assume FINISHED
    disappeared = set(_polled_items.keys()) - set(current.keys())
    for chapter_id in disappeared:
        if chapter_id not in _emitted_error_ids:
            old = _polled_items[chapter_id]
            _dispatch(
                "FINISHED",
                old["chapter_id"],
                old["chapter_name"],
                old["manga_title"],
                old["source_name"],
            )
    # Clean up error tracking for items that have left the queue
    _emitted_error_ids -= disappeared

    # Items in queue with ERROR state not yet dispatched
    for chapter_id, item in current.items():
        if item["state"] == "ERROR" and chapter_id not in _emitted_error_ids:
            _emitted_error_ids.add(chapter_id)
            _dispatch(
                "ERROR",
                item["chapter_id"],
                item["chapter_name"],
                item["manga_title"],
                item["source_name"],
            )

    _polled_items = current


async def _seed_poll() -> None:
    """Snapshot the current download queue on startup.

    Populates ``_polled_items`` so that polling mode can detect disappearances
    even for chapters that were already in the queue before the first WebSocket
    connection attempt. If the seed poll fails the listener starts with an empty
    snapshot — chapters already downloaded before startup will not be re-processed.
    """
    global _polled_items
    try:
        items = await suwayomi.poll_downloads()
        _polled_items = {item["chapter_id"]: item for item in items}
        logger.info(
            "download_listener: seeded %d chapter IDs from initial poll",
            len(_polled_items),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("download_listener: initial poll seed failed: %r", exc)
        _polled_items = {}


async def reconcile_on_startup() -> None:
    """Dispatch FINISHED events for chapters that completed while the backend was down.

    Queries the DB for assignments still in 'queued' or 'downloading' status and
    cross-references them against the current Suwayomi queue snapshot in
    ``_polled_items`` (populated by ``_seed_poll()``). Any assignment absent from
    the current queue is assumed to have finished and gets a FINISHED event
    dispatched. The idempotency guard in chapter_event_handler.handle() silently
    no-ops for chapters that were already processed before the restart.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from ..database import AsyncSessionLocal
    from ..models.chapter_assignment import ChapterAssignment, DownloadStatus

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChapterAssignment)
            .where(
                ChapterAssignment.download_status.in_(
                    [DownloadStatus.queued, DownloadStatus.downloading]
                )
            )
            .options(selectinload(ChapterAssignment.source))
        )
        in_flight = result.scalars().all()

    if not in_flight:
        logger.info("download_listener: reconcile_on_startup: no in-flight chapters")
        return

    current_ids = set(_polled_items.keys())
    missed = [a for a in in_flight if a.suwayomi_chapter_id not in current_ids]

    if not missed:
        logger.info(
            "download_listener: reconcile_on_startup: all %d in-flight chapter(s) still in queue",
            len(in_flight),
        )
        return

    logger.info(
        "download_listener: reconcile_on_startup: dispatching FINISHED for %d chapter(s) "
        "absent from Suwayomi queue",
        len(missed),
    )
    for assignment in missed:
        _dispatch(
            "FINISHED",
            assignment.suwayomi_chapter_id,
            assignment.source_chapter_name or "",
            assignment.source_manga_title or "",
            assignment.source.name,
        )


async def run() -> None:
    """Maintain a persistent connection to Suwayomi's downloadChanged subscription.

    Dispatches FINISHED and ERROR events to chapter_event_handler.handle() via
    asyncio.create_task() so slow relocations do not block the listener.

    State machine:
    - On startup, polls once to snapshot the current queue (see ``_seed_poll``).
    - SUBSCRIPTION mode (default): connect via WebSocket subscription; on failure,
      retry with exponential backoff (2, 4, 8, 16, 30 s cap). After
      MAX_RECONNECT_ATTEMPTS consecutive failures, switch to POLLING mode.
    - POLLING mode (fallback): call poll_downloads() every
      DOWNLOAD_POLL_FALLBACK_SECONDS. FINISHED events are inferred by comparing
      the current queue to the previous snapshot — items that disappear are assumed
      complete. ERROR events are dispatched when an item's state is ERROR.
      On first successful poll, switch back to SUBSCRIPTION mode.
    """
    global _polled_items, _emitted_error_ids
    _polled_items = {}
    _emitted_error_ids = set()

    await _seed_poll()
    await reconcile_on_startup()

    use_polling = False

    while True:
        if not use_polling:
            attempt = 0
            while True:
                try:
                    async for (
                        event_type,
                        chapter_id,
                        chapter_name,
                        manga_title,
                        source_name,
                    ) in suwayomi.subscribe_download_changed():
                        attempt = 0
                        _dispatch(
                            event_type,
                            chapter_id,
                            chapter_name,
                            manga_title,
                            source_name,
                        )
                    # Generator exhausted cleanly — reconnect immediately.
                    attempt = 0
                except (TransportError, ConnectionError, Exception) as exc:
                    attempt += 1
                    logger.warning(
                        "download_listener: subscription error (attempt %d/%d): %r",
                        attempt,
                        settings.MAX_RECONNECT_ATTEMPTS,
                        exc,
                    )
                    if attempt >= settings.MAX_RECONNECT_ATTEMPTS:
                        logger.error(
                            "download_listener: max reconnect attempts reached — "
                            "switching to polling fallback"
                        )
                        use_polling = True
                        break
                    backoff = min(2**attempt, 30)
                    await asyncio.sleep(backoff)
        else:
            # POLLING mode
            while True:
                try:
                    items = await suwayomi.poll_downloads()
                    _process_poll_result(items)
                    # Success — switch back to subscription mode.
                    logger.info(
                        "download_listener: poll succeeded — resuming subscription mode"
                    )
                    use_polling = False
                    break
                except Exception as exc:
                    logger.warning("download_listener: poll error: %r", exc)
                    await asyncio.sleep(settings.DOWNLOAD_POLL_FALLBACK_SECONDS)
