import asyncio
import logging

from gql.transport.exceptions import TransportError

from ..config import settings
from ..services import suwayomi
from . import chapter_event_handler

logger = logging.getLogger(__name__)


async def run() -> None:
    """Maintain a persistent connection to Suwayomi's downloadChanged subscription.

    Dispatches FINISHED events to chapter_event_handler.handle() via asyncio.create_task()
    so slow relocations do not block the listener.

    State machine:
    - SUBSCRIPTION mode (default): connect via WebSocket subscription; on failure, retry
      with exponential backoff (2, 4, 8, 16, 30s cap). After MAX_RECONNECT_ATTEMPTS
      consecutive failures, switch to POLLING mode.
    - POLLING mode (fallback): poll GET /api/v1/downloads every
      DOWNLOAD_POLL_FALLBACK_SECONDS. On first success, switch back to SUBSCRIPTION mode.
    """
    use_polling = False

    while True:
        if not use_polling:
            attempt = 0
            while True:
                try:
                    async for (chapter_id, chapter_name, manga_title, source_name) in (
                        suwayomi.subscribe_download_changed()
                    ):
                        attempt = 0
                        asyncio.create_task(
                            chapter_event_handler.handle(
                                chapter_id, chapter_name, manga_title, source_name
                            )
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
                    backoff = min(2 ** attempt, 30)
                    await asyncio.sleep(backoff)
        else:
            # POLLING mode
            while True:
                try:
                    items = await suwayomi.poll_downloads()
                    for item in items:
                        asyncio.create_task(chapter_event_handler.handle(*item))
                    # Success — switch back to subscription mode.
                    logger.info(
                        "download_listener: poll succeeded — resuming subscription mode"
                    )
                    use_polling = False
                    break
                except Exception as exc:
                    logger.warning("download_listener: poll error: %r", exc)
                    await asyncio.sleep(settings.DOWNLOAD_POLL_FALLBACK_SECONDS)
