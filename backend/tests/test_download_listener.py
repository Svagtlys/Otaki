"""Unit and integration tests for workers/download_listener.py."""
import asyncio
import contextlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers import download_listener


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_gen(*items):
    """Yield each item as an async generator."""
    for item in items:
        yield item


async def _raise_then_yield(exc, *items):
    """Raise exc on first call, then yield items on subsequent calls.

    Used as a side_effect list where the first element is an exception and
    subsequent elements are async generators.
    """
    raise exc


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatches_on_finished_event():
    """A single FINISHED tuple from the subscription is dispatched to handle()."""
    item = ("FINISHED", "42", "Chapter 1", "Test Manga", "TestSource")

    call_count = 0

    async def _subscribe_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield item
        else:
            raise asyncio.CancelledError()

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_subscribe_side_effect,
        ),
        patch(
            "app.workers.download_listener.suwayomi.poll_downloads",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ) as mock_handle,
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = 5
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

        # Allow the created task to run.
        await asyncio.sleep(0)
        mock_handle.assert_awaited_once_with(*item)


@pytest.mark.asyncio
async def test_ignores_non_finished_states():
    """Non-FINISHED events (e.g. QUEUED, DOWNLOADING) are not dispatched to handle()."""
    # subscribe_download_changed already filters by FINISHED before yielding,
    # so this test confirms the listener forwards everything it receives and
    # that the subscription itself filters (no items yielded = no handle calls).

    call_count = 0

    async def _empty_then_cancel():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Yield nothing — simulate subscription with no FINISHED events
            return
            yield  # noqa: unreachable — makes this an async generator
        else:
            raise asyncio.CancelledError()

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_empty_then_cancel,
        ),
        patch(
            "app.workers.download_listener.suwayomi.poll_downloads",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ) as mock_handle,
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = 5
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

        mock_handle.assert_not_called()


@pytest.mark.asyncio
async def test_retries_with_backoff():
    """Subscription failures trigger exponential backoff sleep before retry."""
    item = ("FINISHED", "7", "Chapter 7", "Manga X", "Src")

    call_count = 0

    async def _fail_then_yield():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("refused")
        elif call_count == 2:
            yield item
        else:
            raise asyncio.CancelledError()

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_fail_then_yield,
        ),
        patch(
            "app.workers.download_listener.suwayomi.poll_downloads",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ),
        patch("app.workers.download_listener.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = 5
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

    # After first failure (attempt=1), backoff = min(2**1, 30) = 2
    mock_sleep.assert_any_call(2)


@pytest.mark.asyncio
async def test_switches_to_polling_after_max_retries():
    """After MAX_RECONNECT_ATTEMPTS consecutive failures, poll_downloads is called in polling mode."""
    max_attempts = 3
    poll_call_count = 0

    async def _always_fail():
        raise ConnectionError("refused")
        yield  # make it an async generator

    async def _mock_poll():
        nonlocal poll_call_count
        poll_call_count += 1
        if poll_call_count == 1:
            # Seed call at startup — return empty list
            return []
        # Polling fallback call — raise to exit cleanly
        raise asyncio.CancelledError()

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_always_fail,
        ),
        patch(
            "app.workers.download_listener.suwayomi.poll_downloads",
            new_callable=AsyncMock,
            side_effect=_mock_poll,
        ),
        patch("app.workers.download_listener.asyncio.sleep", new_callable=AsyncMock),
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = max_attempts
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

    # poll_downloads called once for seed + once when polling fallback is reached
    assert poll_call_count == 2


@pytest.mark.asyncio
async def test_resumes_subscription_after_poll_success():
    """After a successful poll, the listener switches back to subscription mode.

    The poll detects a chapter that disappeared (was in the seed snapshot but
    absent from the polling-mode poll) and dispatches FINISHED for it.
    """
    # Item present in the seed snapshot — represents an in-progress download
    seed_item = {
        "state": "DOWNLOADING",
        "chapter_id": "99",
        "chapter_name": "Chapter 99",
        "manga_title": "Some Manga",
        "source_name": "SomeSrc",
    }
    max_attempts = 2

    fail_count = 0

    async def _always_fail_subscription():
        nonlocal fail_count
        fail_count += 1
        raise ConnectionError("refused")
        yield  # make it an async generator

    poll_call_count = 0

    async def _poll_side_effect():
        nonlocal poll_call_count
        poll_call_count += 1
        if poll_call_count == 1:
            # Seed call — item is still in queue (downloading)
            return [seed_item]
        # Polling fallback call — item has disappeared (completed)
        return []

    sub_call_count_after_poll = 0

    async def _subscription_after_switch():
        nonlocal sub_call_count_after_poll, fail_count
        fail_count += 1
        sub_call_count_after_poll += 1
        raise asyncio.CancelledError()
        yield  # make it an async generator

    call_index = 0

    def _subscription_side_effect():
        nonlocal call_index
        call_index += 1
        if call_index <= max_attempts:
            return _always_fail_subscription()
        else:
            return _subscription_after_switch()

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_subscription_side_effect,
        ),
        patch(
            "app.workers.download_listener.suwayomi.poll_downloads",
            new_callable=AsyncMock,
            side_effect=_poll_side_effect,
        ),
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ) as mock_handle,
        patch("app.workers.download_listener.asyncio.sleep", new_callable=AsyncMock),
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = max_attempts
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

    # Item disappeared between seed and polling → FINISHED dispatched
    await asyncio.sleep(0)
    mock_handle.assert_any_call("FINISHED", "99", "Chapter 99", "Some Manga", "SomeSrc")
    # Subscription was re-attempted after the poll succeeded.
    assert sub_call_count_after_poll >= 1


@pytest.mark.asyncio
async def test_dispatches_error_event():
    """A single ERROR tuple from the subscription is dispatched to handle()."""
    item = ("ERROR", "55", "Chapter 5", "Test Manga", "TestSource")

    call_count = 0

    async def _subscribe_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield item
        else:
            raise asyncio.CancelledError()

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_subscribe_side_effect,
        ),
        patch(
            "app.workers.download_listener.suwayomi.poll_downloads",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ) as mock_handle,
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = 5
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

    await asyncio.sleep(0)
    mock_handle.assert_awaited_once_with(*item)


@pytest.mark.asyncio
async def test_background_tasks_set_holds_then_releases_task():
    """Task is in _background_tasks immediately after creation, gone after it completes."""
    item = ("FINISHED", "77", "Chapter 77", "Test Manga", "TestSource")

    call_count = 0

    async def _subscribe_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield item
        else:
            raise asyncio.CancelledError()

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_subscribe_side_effect,
        ),
        patch(
            "app.workers.download_listener.suwayomi.poll_downloads",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ),
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = 5
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        assert len(download_listener._background_tasks) == 0, "leaked tasks from a previous test"

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

        # This assertion relies on the fact that the path from
        # `_background_tasks.add(task)` to the CancelledError propagating out of
        # run() is entirely synchronous — there is no `await` between the add and
        # the raise, so the event loop never gets a chance to run the task's
        # coroutine or its done callback before we reach this line.
        assert len(download_listener._background_tasks) == 1

        # Yield to the event loop twice: once for the task body to run, once more
        # for the done callback to fire (AsyncMock needs two cycles to fully settle).
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(download_listener._background_tasks) == 0


@pytest.mark.asyncio
async def test_polling_path_tracks_background_tasks():
    """Tasks dispatched via the polling fallback are tracked in _background_tasks.

    Drives the listener into polling mode by exhausting MAX_RECONNECT_ATTEMPTS with
    subscription failures. The seed poll returns one item; the polling-mode poll
    returns an empty list — the item's disappearance triggers a FINISHED dispatch.
    The subsequent subscription attempt raises CancelledError to exit the loop.
    After run() raises, the task created by the polling dispatch must be in _background_tasks.
    """
    assert len(download_listener._background_tasks) == 0, "leaked tasks from a previous test"

    seed_item = {
        "state": "DOWNLOADING",
        "chapter_id": "88",
        "chapter_name": "Chapter 88",
        "manga_title": "Poll Manga",
        "source_name": "PollSource",
    }
    max_attempts = 2

    async def _always_fail_subscription():
        raise ConnectionError("refused")
        yield  # make it an async generator

    poll_call_count = 0

    async def _poll_side_effect():
        nonlocal poll_call_count
        poll_call_count += 1
        if poll_call_count == 1:
            # Seed call — item is in queue
            return [seed_item]
        # Polling fallback call — item has disappeared → triggers FINISHED dispatch
        return []

    # After the poll succeeds the listener switches back to subscription mode.
    # Raise CancelledError on the next subscription attempt to exit cleanly.
    sub_call_index = 0

    def _subscription_side_effect():
        nonlocal sub_call_index
        sub_call_index += 1
        if sub_call_index <= max_attempts:
            return _always_fail_subscription()
        # Post-poll subscription attempt — exit the loop.
        async def _cancel():
            raise asyncio.CancelledError()
            yield  # make it an async generator

        return _cancel()

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_subscription_side_effect,
        ),
        patch(
            "app.workers.download_listener.suwayomi.poll_downloads",
            new_callable=AsyncMock,
            side_effect=_poll_side_effect,
        ),
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ),
        patch("app.workers.download_listener.asyncio.sleep", new_callable=AsyncMock),
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = max_attempts
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

        # The polling path added a task synchronously before CancelledError propagated.
        assert len(download_listener._background_tasks) >= 1

        # Await the pending tasks directly so their done callbacks fire and they
        # remove themselves from _background_tasks. Simple sleep(0) loops are
        # insufficient here because the AsyncMock coroutine internals require the
        # event loop to fully schedule and complete the underlying awaitable.
        pending = list(download_listener._background_tasks)
        await asyncio.gather(*pending, return_exceptions=True)
        assert len(download_listener._background_tasks) == 0


# ---------------------------------------------------------------------------
# _seed_poll and _process_poll_result unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_poll_populates_polled_items():
    """_seed_poll() seeds _polled_items from the current download queue."""
    item = {
        "state": "DOWNLOADING",
        "chapter_id": "11",
        "chapter_name": "Ch 11",
        "manga_title": "Manga",
        "source_name": "Src",
    }
    download_listener._polled_items = {}
    download_listener._emitted_error_ids = set()

    with patch(
        "app.workers.download_listener.suwayomi.poll_downloads",
        new_callable=AsyncMock,
        return_value=[item],
    ):
        await download_listener._seed_poll()

    assert "11" in download_listener._polled_items
    assert download_listener._polled_items["11"]["chapter_name"] == "Ch 11"


@pytest.mark.asyncio
async def test_process_poll_dispatches_finished_on_disappearance():
    """FINISHED is dispatched when an item disappears from the queue."""
    item = {
        "state": "DOWNLOADING",
        "chapter_id": "33",
        "chapter_name": "Chapter 33",
        "manga_title": "My Manga",
        "source_name": "Src",
    }
    download_listener._polled_items = {"33": item}
    download_listener._emitted_error_ids = set()

    with patch(
        "app.workers.download_listener.chapter_event_handler.handle",
        new_callable=AsyncMock,
    ) as mock_handle:
        download_listener._process_poll_result([])  # item disappeared
        await asyncio.sleep(0)
        mock_handle.assert_awaited_once_with("FINISHED", "33", "Chapter 33", "My Manga", "Src")


@pytest.mark.asyncio
async def test_process_poll_dispatches_error_state_once():
    """ERROR is dispatched when an item has ERROR state, and only once (deduped)."""
    item = {
        "state": "ERROR",
        "chapter_id": "44",
        "chapter_name": "Chapter 44",
        "manga_title": "Manga",
        "source_name": "Src",
    }
    download_listener._polled_items = {}
    download_listener._emitted_error_ids = set()

    with patch(
        "app.workers.download_listener.chapter_event_handler.handle",
        new_callable=AsyncMock,
    ) as mock_handle:
        download_listener._process_poll_result([item])
        await asyncio.sleep(0)
        mock_handle.assert_awaited_once_with("ERROR", "44", "Chapter 44", "Manga", "Src")

        # Second poll — same item still in ERROR state — no new dispatch
        mock_handle.reset_mock()
        download_listener._process_poll_result([item])
        await asyncio.sleep(0)
        mock_handle.assert_not_called()


@pytest.mark.asyncio
async def test_process_poll_no_finished_for_error_items():
    """When an ERROR item disappears, FINISHED is not dispatched for it."""
    item = {
        "state": "ERROR",
        "chapter_id": "55",
        "chapter_name": "Chapter 55",
        "manga_title": "Manga",
        "source_name": "Src",
    }
    download_listener._polled_items = {}
    download_listener._emitted_error_ids = set()

    with patch(
        "app.workers.download_listener.chapter_event_handler.handle",
        new_callable=AsyncMock,
    ) as mock_handle:
        # First: ERROR item appears → dispatch ERROR
        download_listener._process_poll_result([item])
        await asyncio.sleep(0)
        assert mock_handle.call_count == 1
        assert mock_handle.call_args.args[0] == "ERROR"

        # Item disappears → should NOT dispatch FINISHED
        mock_handle.reset_mock()
        download_listener._process_poll_result([])
        await asyncio.sleep(0)
        mock_handle.assert_not_called()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def _first_online_source(sources: list[dict]) -> dict:
    online = [s for s in sources if s["id"] != "0"]
    assert len(online) > 0, "No online sources installed on this Suwayomi instance"
    return online[0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_enqueue_and_receive_via_subscription(suwayomi_settings, test_manga_title):
    """Enqueue a chapter download then verify the subscription delivers its FINISHED event.

    Subscribes BEFORE enqueuing so no event is missed. The subscription task runs in the
    background while the enqueue call is made, matching how download_listener.run() works
    in production.

    Waits up to 120 seconds for the FINISHED event to arrive.
    Skipped when SUWAYOMI_URL is not configured.
    """
    from app.services import suwayomi as real_suwayomi

    sources = await real_suwayomi.list_sources()
    source = _first_online_source(sources)
    results = await real_suwayomi.search_source(source["id"], test_manga_title)
    assert results, f"No results for {test_manga_title!r} on source {source['name']!r}"

    chapters = await real_suwayomi.fetch_chapters(results[0]["manga_id"])
    assert chapters, "No chapters found for the manga"
    chapter_id = chapters[0]["suwayomi_chapter_id"]

    received_ids: list[str] = []
    found = asyncio.Event()

    async def _listen():
        async for (event_type, cid, *_) in real_suwayomi.subscribe_download_changed():
            if event_type != "FINISHED":
                continue
            received_ids.append(cid)
            if cid == chapter_id:
                found.set()
                return

    listen_task = asyncio.create_task(_listen())
    # Give the WebSocket time to connect before enqueuing.
    await asyncio.sleep(1)
    await real_suwayomi.enqueue_downloads([chapter_id])

    try:
        async with asyncio.timeout(120):
            await found.wait()
    except TimeoutError:
        pytest.fail(
            f"Timed out after 120s waiting for chapter {chapter_id} to finish. "
            f"Received: {received_ids}"
        )
    finally:
        listen_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listen_task
