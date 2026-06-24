# Design: Fix SQLite "database is locked" Error During Bulk Downloads

**Issue:** #171 — Database lock error
**Branch:** fix/171-database-lock
**Date:** 2026-06-24

## Problem

The backend throws SQLite "database is locked" errors during bulk chapter assignment status updates. The error occurs in `chapter_event_handler.handle()` when multiple concurrent calls (8+ chapters completing at once) compete for the `write_session()` asyncio lock.

### Root Cause

[`chapter_event_handler.handle()`](backend/app/workers/chapter_event_handler.py:48) acquires a `write_session()` lock and holds it for the entire post-download pipeline:

1. Query assignment, mark `download_status=done`
2. **Run `file_relocator.relocate()` — 2–5 seconds of disk I/O**
3. Set `is_active=True`, commit

With 8+ concurrent `handle()` calls dispatched by [`download_listener._dispatch()`](backend/app/workers/download_listener.py:42), each call holds the lock for seconds. The 8th+ caller times out waiting for the lock because the prior 7 calls are sequentially blocked on file I/O.

### Why Existing Protections Don't Help

- **WAL mode** — allows concurrent reads but still serializes writes. Secondary concern — the real bottleneck is above SQLite.
- **`asyncio.Lock` in `write_session()`** — serializes all worker writes at the Python level. When `handle()` holds this lock during 2-5 second file I/O, other `handle()` calls block on the asyncio lock and never reach SQLite at all. This is the primary bottleneck.
- **`connect_args timeout=30`** — SQLite-level timeout is irrelevant since callers are blocked by the asyncio lock before reaching the database>>>>>>> REPLACE

## Solution: Three-Phase `handle()`

Split `handle()` into three phases with explicit `write_session()` boundaries:

```
Phase 1 — DB (brief lock)
  ├─ query assignment
  ├─ mark download_status=done, downloaded_at
  ├─ query comic, determine swap decision
  └─ commit()

Phase 2 — File I/O (no lock)
  └─ file_relocator.relocate() or replace_in_library()

Phase 3 — DB (brief lock)
  ├─ set is_active=True/False based on swap decision
  ├─ update relocation_status
  └─ commit()
```

Each DB phase holds the lock for <100ms. File I/O runs outside the lock, so 8 concurrent calls can do disk work in parallel.

## Components

### Modified: `chapter_event_handler.handle()`

Refactored into three phases. Key changes:

1. **Phase 1** moves all DB queries and status updates into a single `write_session()` block that commits before any file I/O
2. **Phase 2** runs file I/O outside any database session
3. **Phase 3** acquires `write_session()` to finalize `is_active` and `relocation_status`

The swap decision logic (comparing effective priorities) is computed in Phase 1 but the file swap action happens in Phase 2. Phase 3 records the outcome.

### Unchanged

- [`_handle_error()`](backend/app/workers/chapter_event_handler.py:166) — already DB-only
- [`_retry_download()`](backend/app/workers/chapter_event_handler.py:226) — already DB-only
- [`download_listener._dispatch()`](backend/app/workers/download_listener.py:31) — no changes needed
- [`file_relocator`](backend/app/services/file_relocator.py) — no interface changes

## Error Handling

- If file I/O fails after Phase 1, the assignment is in `download_status=done` with `relocation_status=pending` — this is the existing behavior (exceptions are caught at line 144 and logged)
- Phase 3 updates `relocation_status=failed` if file I/O set it during error handling
- No new failure modes introduced

## Testing

- Existing concurrency test [`test_handle_concurrent_calls_do_not_raise`](backend/tests/test_chapter_event_handler.py:666) should continue passing
- Add test: verify intermediate state after Phase 1 (assignment is `done` but `is_active=False` before file I/O completes)
- Add test: verify file I/O failure leaves assignment in `done/failed` state with correct logging

## Risks

- **File I/O failure after Phase 1 commit:** Assignment shows `download_status=done` but file is not in library. Mitigated by existing `relocation_status` tracking and logging.
- **Race condition during upgrade swap:** Two concurrent downloads for the same chapter could both complete Phase 1 before either runs file I/O. The existing swap logic already handles this by comparing effective priorities and checking `existing_active` state.

## Non-Goals

- This fix does not address `get_db()` bypassing the write lock in API routes (separate issue)
- This fix does not add retry logic with backoff (can be added later as a safety net)
