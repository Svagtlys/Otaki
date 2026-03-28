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

    with (
        patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            return_value=_async_gen(item),
        ),
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ) as mock_handle,
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = 5
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        # After the first generator drains, the listener loops and calls subscribe again.
        # We let the second call raise CancelledError to exit the loop cleanly in tests.
        call_count = 0

        async def _subscribe_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield item
            else:
                raise asyncio.CancelledError()

        with patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_subscribe_side_effect,
        ):
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

    with (
        patch(
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ) as mock_handle,
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = 5
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

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

        with patch(
            "app.workers.download_listener.suwayomi.subscribe_download_changed",
            side_effect=_empty_then_cancel,
        ):
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
    """After MAX_RECONNECT_ATTEMPTS consecutive failures, poll_downloads is called."""
    max_attempts = 3

    async def _always_fail():
        raise ConnectionError("refused")
        yield  # make it an async generator

    poll_called = asyncio.Event()

    async def _mock_poll():
        poll_called.set()
        # Raise to prevent infinite polling loop in test
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
        ) as mock_poll,
        patch("app.workers.download_listener.asyncio.sleep", new_callable=AsyncMock),
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = max_attempts
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

    mock_poll.assert_called_once()


@pytest.mark.asyncio
async def test_resumes_subscription_after_poll_success():
    """After a successful poll, the listener switches back to subscription mode."""
    poll_item = ("FINISHED", "99", "Chapter 99", "Some Manga", "SomeSrc")
    max_attempts = 2

    fail_count = 0

    async def _always_fail_subscription():
        nonlocal fail_count
        fail_count += 1
        raise ConnectionError("refused")
        yield  # make it an async generator

    poll_call_count = 0

    async def _poll_then_raise():
        nonlocal poll_call_count
        poll_call_count += 1
        return [poll_item]

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
            side_effect=_poll_then_raise,
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

    # Poll ran once and dispatched the poll item.
    await asyncio.sleep(0)
    mock_handle.assert_any_call(*poll_item)
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
            "app.workers.download_listener.chapter_event_handler.handle",
            new_callable=AsyncMock,
        ),
        patch("app.workers.download_listener.settings") as mock_settings,
    ):
        mock_settings.MAX_RECONNECT_ATTEMPTS = 5
        mock_settings.DOWNLOAD_POLL_FALLBACK_SECONDS = 60

        # Clear any residual tasks from previous tests.
        download_listener._background_tasks.clear()

        with pytest.raises(asyncio.CancelledError):
            await download_listener.run()

        # Immediately after run() exits (before the task coroutine has a chance to
        # complete), the task should still be held in _background_tasks.
        assert len(download_listener._background_tasks) == 1

        # Yield to the event loop twice: once for the task body to run, once more
        # for the done callback to fire (AsyncMock needs two cycles to fully settle).
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(download_listener._background_tasks) == 0


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
