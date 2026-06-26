# Database Lock Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate SQLite "database is locked" errors during bulk download completion by splitting `chapter_event_handler.handle()` into three phases that minimize `write_session` asyncio lock hold time.

**Architecture:** Refactor `handle()` so that file I/O runs outside the `write_session()` asyncio lock. Phase 1 (locked session) marks the assignment as done and computes the swap decision. Phase 2 (unlocked session) runs `file_relocator.relocate()` or `replace_in_library()` — bypassing `write_session()` entirely and using `AsyncSessionLocal()` directly. Phase 3 (locked session) finalizes `is_active` and `relocation_status`. Each locked phase holds the asyncio lock for <100ms instead of 2-5 seconds.

**Why splitting phases helps (and what the bottleneck actually is):** The bottleneck is the [`asyncio.Lock`](backend/app/database.py:20) inside [`write_session()`](backend/app/database.py:50), not SQLite's own writer serialization. When `handle()` holds `write_session()` during 2–5 second file I/O, other concurrent `handle()` calls block on the asyncio lock and never even reach SQLite. By releasing the asyncio lock between Phase 1 and Phase 2, other coroutines can acquire the lock and perform their own Phase 1 DB work while the first call is stuck in file I/O. SQLite WAL mode is a secondary benefit — it allows the Phase 2 unlocked session to read/write without blocking other sessions — but the primary fix is reducing asyncio lock hold time.>>>>>>> REPLACE

**Tech Stack:** Python 3.13, SQLAlchemy async, aiosqlite, pytest-asyncio

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Modify | `backend/app/workers/chapter_event_handler.py` | Split `handle()` into three phases |
| Modify | `backend/tests/test_chapter_event_handler.py` | Update existing tests, add new tests |

---

### Task 1: Write test for three-phase intermediate state

**Files:**
- Modify: `backend/tests/test_chapter_event_handler.py`

This test verifies that after Phase 1, the assignment is marked `download_status=done` but file I/O has not yet run. After Phase 3, `is_active=True` and `relocation_status` is set correctly.

- [ ] **Step 1: Add test for three-phase intermediate state**

Add this test to `backend/tests/test_chapter_event_handler.py` after the existing `test_handle_regular_download` test (around line 180):

```python
@pytest.mark.asyncio
async def test_handle_three_phase_intermediate_state(handler_db, monkeypatch):
    """Phase 1 should commit download_status=done before file I/O runs."""
    comic_id, source_id = await _seed_comic(handler_db)

    async with handler_db() as db:
        assignment = _make_assignment(
            comic_id, source_id, chapter_id="ch-three-phase", is_active=False
        )
        db.add(assignment)
        await db.commit()
        assignment_id = assignment.id

    # Patch file_relocator.relocate to verify Phase 1 committed before file I/O
    phase1_committed = False

    async def tracking_relocate(*args, **kwargs):
        nonlocal phase1_committed
        # At this point, Phase 1 should have committed download_status=done
        async with handler_db() as verify_db:
            a = await verify_db.get(ChapterAssignment, assignment_id)
            assert a.download_status == DownloadStatus.done
            # is_active should NOT be set yet — file I/O hasn't completed
            assert a.is_active is False
            phase1_committed = True

    monkeypatch.setattr(
        chapter_event_handler.file_relocator, "relocate", tracking_relocate
    )

    await chapter_event_handler.handle(
        "FINISHED", "ch-three-phase", "Chapter 1", "Test Comic", "TestSrc"
    )

    assert phase1_committed is True

    async with handler_db() as db:
        result = await db.get(ChapterAssignment, assignment_id)
        assert result.download_status == DownloadStatus.done
        assert result.is_active is True
```

- [ ] **Step 2: Run test to verify it fails (before implementation)**

Run:
```bash
cd backend && .venv/bin/pytest tests/test_chapter_event_handler.py::test_handle_three_phase_intermediate_state -v
```

Expected: The test will fail because the current implementation does file I/O inside the lock, so `is_active=True` will already be set when `tracking_relocate` runs. The `assert a.is_active is False` line will fail.

- [ ] **Step 3: Commit the failing test**

```bash
git add backend/tests/test_chapter_event_handler.py
git commit -m "test: add three-phase intermediate state test (fails)"
```

---

### Task 2: Refactor `handle()` into three phases

**Files:**
- Modify: `backend/app/workers/chapter_event_handler.py`

Replace the FINISHED path in `handle()` (lines 47-163) with three-phase logic.

**Key design decision:** Phase 2 uses `AsyncSessionLocal()` directly (bypassing the `write_session` lock) because:
- The `asyncio.Lock` inside `write_session()` is the bottleneck — holding it during file I/O serializes all concurrent `handle()` calls at the Python level
- By bypassing `write_session()` and using `AsyncSessionLocal()` directly, Phase 2 releases the asyncio lock so other `handle()` calls can perform their Phase 1 DB work
- `file_relocator.relocate()` runs file I/O via `asyncio.to_thread()` which yields to the event loop, allowing other coroutines to schedule
- SQLite WAL mode is a secondary benefit — it ensures Phase 2's unlocked session doesn't conflict with Phase 1 sessions from other calls>>>>>>> REPLACE

- [ ] **Step 1: Add import for `AsyncSessionLocal`**

At the top of `chapter_event_handler.py`, add this import:

```python
from ..database import AsyncSessionLocal, write_session
```

- [ ] **Step 2: Replace the FINISHED path with three-phase implementation**

Replace lines 47-163 in `backend/app/workers/chapter_event_handler.py` with:

```python
    # FINISHED path — three-phase execution to minimize lock hold time
    # Phase 1: DB (locked) — mark done, compute swap decision, commit immediately
    phase_data = None

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

        # Check whether this is an upgrade download
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

        # Compute swap decision without running file I/O
        if existing_active is None:
            action = "relocate"
            should_swap = True
            existing_active_id = None
        else:
            existing_failed = (
                existing_active.download_status == DownloadStatus.failed
                or existing_active.relocation_status == RelocationStatus.failed
            )

            if existing_failed:
                should_swap = True
            else:
                from ..services import source_selector

                incoming_priority = await source_selector.effective_priority(
                    assignment.source, comic, db
                )
                existing_priority = await source_selector.effective_priority(
                    existing_active.source, comic, db
                )
                should_swap = incoming_priority < existing_priority

            if should_swap:
                action = "swap"
                existing_active_id = existing_active.id
            else:
                action = "no_swap"
                existing_active_id = None
                logger.info(
                    "handle: incoming from lower-priority source (priority=%d vs %d) "
                    "— marking done but keeping existing active",
                    assignment.source.priority,
                    existing_active.source.priority,
                )

        # Commit Phase 1: assignment is now download_status=done
        await db.commit()

        phase_data = {
            "assignment_id": assignment.id,
            "comic": comic,
            "action": action,
            "should_swap": should_swap,
            "existing_active_id": existing_active_id,
            "source_display_name": source_display_name,
            "comic_title": comic.title,
            "chapter_name": chapter_name,
        }

    # Phase 2: File I/O — bypasses write_session() asyncio lock so other
    # handle() calls can perform Phase 1 DB work in parallel.
    # Uses AsyncSessionLocal() directly since the asyncio lock is the
    # bottleneck (not SQLite itself), and file I/O yields via asyncio.to_thread().>>>>>>> REPLACE
    if phase_data is None:
        return

    relocation_failed = False
    async with AsyncSessionLocal() as db:
        assignment = await db.get(ChapterAssignment, phase_data["assignment_id"])
        try:
            if phase_data["action"] == "relocate":
                await file_relocator.relocate(
                    assignment,
                    phase_data["comic"],
                    db,
                    source_display_name=phase_data["source_display_name"],
                )
                assignment.is_active = True
            elif phase_data["action"] == "swap":
                existing_active = await db.get(
                    ChapterAssignment, phase_data["existing_active_id"]
                )
                await file_relocator.replace_in_library(
                    existing_active,
                    assignment,
                    phase_data["comic"],
                    db,
                    source_display_name=phase_data["source_display_name"],
                )
                existing_active.is_active = False
                assignment.is_active = True
            else:
                # no_swap — mark done but keep inactive
                assignment.is_active = False

            await db.commit()
        except Exception:
            relocation_failed = True
            await db.rollback()
            logger.exception(
                "handle: relocation raised for chapter_id=%s comic=%r chapter=%s — "
                "assignment left in download_status=done, relocation_status=%s",
                suwayomi_chapter_id,
                phase_data["comic_title"],
                phase_data["chapter_name"],
                assignment.relocation_status,
            )

    # Phase 3: Log relocation failure warning (no DB write needed)
    if not relocation_failed:
        async with write_session() as db:
            assignment = await db.get(ChapterAssignment, phase_data["assignment_id"])
            if assignment and assignment.relocation_status == RelocationStatus.failed:
                logger.warning(
                    "handle: relocation failed for chapter_id=%s comic=%r chapter=%s "
                    "(staging file not found or path error)",
                    suwayomi_chapter_id,
                    phase_data["comic_title"],
                    phase_data["chapter_name"],
                )
```

- [ ] **Step 3: Run existing tests to check for regressions**

Run:
```bash
cd backend && .venv/bin/pytest tests/test_chapter_event_handler.py -v
```

Expected: All tests should pass. The three-phase split maintains the same observable behavior (same DB state before/after) but changes the internal ordering.

- [ ] **Step 4: Run the new intermediate state test**

Run:
```bash
cd backend && .venv/bin/pytest tests/test_chapter_event_handler.py::test_handle_three_phase_intermediate_state -v
```

Expected: PASS — Phase 1 now commits before file I/O runs.

- [ ] **Step 5: Commit the implementation**

```bash
git add backend/app/workers/chapter_event_handler.py
git commit -m "fix: split handle() into three phases to reduce SQLite lock contention

Phase 1 (locked session): mark download_status=done, compute swap decision, commit
Phase 2 (unlocked session): run file I/O via asyncio.to_thread()
Phase 3 (locked session): log failure warnings

This eliminates 'database is locked' errors during bulk download completion
by reducing lock hold time from seconds to milliseconds."
```

---

### Task 3: Verify concurrency test still passes

**Files:**
- Test: `backend/tests/test_chapter_event_handler.py`

- [ ] **Step 1: Run the concurrency test**

Run:
```bash
cd backend && .venv/bin/pytest tests/test_chapter_event_handler.py::test_handle_concurrent_calls_do_not_raise -v
```

Expected: PASS — the three-phase split should make concurrent calls even more robust since each phase holds the lock for less time.

- [ ] **Step 2: Run full test suite**

Run:
```bash
cd backend && .venv/bin/pytest -v
```

Expected: All tests pass. No regressions.

- [ ] **Step 3: Run linter**

Run:
```bash
cd backend && .venv/bin/ruff check app/workers/chapter_event_handler.py
```

Expected: No lint errors. Fix any issues if reported.

- [ ] **Step 4: Final commit**

```bash
git add backend/
git commit -m "test: verify concurrency and full test suite pass after three-phase refactor"
```

---

### Task 4: Push and update PR

- [ ] **Step 1: Push changes**

```bash
git push origin fix/171-database-lock
```

- [ ] **Step 2: Update PR description**

Update the draft PR at https://github.com/Svagtlys/Otaki/pull/184 with a summary:

```markdown
## What

Fix SQLite "database is locked" errors during bulk download completion (8+ chapters).

## Root Cause

`chapter_event_handler.handle()` held the `write_session()` asyncio lock during file I/O (2-5 seconds per chapter). The bottleneck is the [`asyncio.Lock`](backend/app/database.py:20) inside `write_session()`, not SQLite's writer serialization. With 8+ concurrent calls dispatched by `download_listener`, each call holds the asyncio lock for seconds. The 8th+ caller blocks on the asyncio lock and never even reaches SQLite, eventually timing out.

## Fix

Split `handle()` into three phases:
1. **Phase 1** (locked session): Mark `download_status=done`, compute swap decision, commit immediately — releases asyncio lock
2. **Phase 2** (unlocked session): Bypass `write_session()` entirely, use `AsyncSessionLocal()` directly for file I/O — allows other `handle()` calls to acquire the asyncio lock and run their Phase 1
3. **Phase 3** (locked session): Log failure warnings

Each locked phase holds the asyncio lock for <100ms instead of 2-5 seconds. SQLite WAL mode is a secondary benefit ensuring Phase 2's unlocked session doesn't conflict with other sessions.>>>>>>> REPLACE

## Testing

- Added `test_handle_three_phase_intermediate_state` to verify Phase 1 commits before file I/O
- Existing concurrency test (`test_handle_concurrent_calls_do_not_raise`) continues to pass
- Full test suite passes
```

---

## Self-Review

**1. Spec coverage:**
- [x] Three-phase split implemented in Task 2
- [x] Intermediate state test in Task 1
- [x] Concurrency test verification in Task 3
- [x] Error handling preserved (relocation_failed path)

**2. Placeholder scan:**
- [x] No "TBD", "TODO", or vague steps
- [x] All code blocks are complete
- [x] All commands are exact

**3. Type consistency:**
- [x] `phase_data` dict structure consistent between Phase 1 and Phase 2
- [x] `action` values ("relocate", "swap", "no_swap") match between phases
- [x] `existing_active_id` flows correctly through phases

**4. Edge cases:**
- [x] `no_swap` path handled (assignment marked `is_active=False`)
- [x] Exception handling in Phase 2 includes `db.rollback()`
- [x] Duplicate FINISHED event still short-circuits in Phase 1
