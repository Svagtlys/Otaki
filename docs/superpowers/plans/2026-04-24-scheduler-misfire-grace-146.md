# Scheduler Misfire Grace Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure overdue polls are not silently dropped on startup by correctly handling APScheduler `misfire_grace_time` and adding catch‑up logic.

**Architecture:** Adjust the scheduler startup to process any missed poll/upgrade jobs that occurred while the service was down. Add explicit `misfire_grace_time` configuration to jobs and safeguard against null `next_*_at` values.

**Tech Stack:** Python 3.11, APScheduler, SQLAlchemy (Async), Otaki backend.

---

### Task 1: Add `misfire_grace_time` to job registration

**Files:**
- Modify: `backend/app/workers/scheduler.py` (lines where `scheduler.add_job` is called for poll and upgrade jobs)
- Test: `backend/tests/workers/test_scheduler.py`

- [ ] **Step 1: Write failing test**
```python
def test_poll_job_has_misfire_grace_time(monkeypatch):
    # Setup scheduler in a fresh state
    from otaki.workers import scheduler as sched_mod
    sched_mod.scheduler.remove_all_jobs()
    # Register a dummy poll job via internal helper
    comic = DummyComic(id=1, next_poll_at=datetime.utcnow() - timedelta(hours=2))
    sched_mod._register_poll_job(comic)
    job = sched_mod.scheduler.get_job(f"poll_{comic.id}")
    assert job.misfire_grace_time == 3600  # 1 hour expected
```
- [ ] **Step 2: Run test to verify it fails** (expect failure because `misfire_grace_time` not set)
- [ ] **Step 3: Implement `misfire_grace_time` parameter** – update both `_register_poll_job` and `_register_upgrade_job` calls to include `misfire_grace_time=3600` (1 hour). Add comment explaining rationale.
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**

### Task 2: Add catch‑up logic on startup

**Files:**
- Modify: `backend/app/workers/scheduler.py` – `start` function
- Add helper: `_process_missed_jobs()` in same file
- Test: `backend/tests/workers/test_scheduler_startup.py`

- [ ] **Step 1: Write failing test**
```python
def test_start_processes_missed_poll(monkeypatch, async_session):
    # Simulate a comic whose next_poll_at is in the past
    comic = Comic(id=2, status=ComicStatus.tracking, next_poll_at=datetime.utcnow() - timedelta(days=1))
    async_session.add(comic)
    await async_session.commit()
    # Patch _poll_comic to record invocation instead of real work
    calls = []
    async def fake_poll(comic_id):
        calls.append(comic_id)
    monkeypatch.setattr(sched_mod, "_poll_comic", fake_poll)
    await sched_mod.start(async_session)
    assert 2 in calls  # poll should have run immediately
```
- [ ] **Step 2: Run test to verify it fails** (no processing of missed jobs)
- [ ] **Step 3: Implement `_process_missed_jobs`** – after loading comics, iterate over each comic, if `next_poll_at` or `next_upgrade_check_at` is in the past, immediately schedule the job with `run_date=datetime.now(timezone.utc)` and invoke the corresponding coroutine (`_poll_comic`/`_upgrade_comic`) via `asyncio.create_task` or `await` inside start loop.
- [ ] **Step 4: Call `_process_missed_jobs`** right after registering jobs in `start` before `scheduler.start()`.
- [ ] **Step 5: Run test to verify it passes**
- [ ] **Step 6: Commit**

### Task 3: Update documentation

**Files:**
- Edit: `docs/ARCHITECTURE.md` – section *Scheduler* to mention `misfire_grace_time` and startup catch‑up behavior.
- Edit: `docs/API.md` – note that poll/upgrade endpoints may be triggered on startup if overdue.

- [ ] **Step 1: Add documentation updates** (no test needed)
- [ ] **Step 2: Commit**

### Task 4: Verify overall integration

**Files:**
- Test: `backend/tests/integration/test_scheduler_integration.py`

- [ ] **Step 1: Write integration test** ensuring that when the service restarts after a downtime, overdue polls are processed and no errors are logged.
- [ ] **Step 2: Run test, expect failure**
- [ ] **Step 3: Ensure logs contain info about missed job processing** (use `caplog`).
- [ ] **Step 4: Run test, expect pass**
- [ ] **Step 5: Commit**

---

**Execution Handoff**

Plan complete and saved to `docs/superpowers/plans/2026-04-24-scheduler-misfire-grace-146.md`. Two execution options:

1. **Subagent‑Driven (recommended)** – dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** – execute tasks sequentially in this session using `superpowers:executing-plans`.

Which approach would you like to use?