# AGENTS.md - Code Mode Rules

This file provides coding guidance specific to this repository.

## Running Backend Commands

**ALL backend Python commands MUST use the virtual environment at `backend/.venv/`.** Prefix with `backend/.venv/bin/` (e.g., `backend/.venv/bin/pytest`, `backend/.venv/bin/uvicorn`, `backend/.venv/bin/ruff`). Do NOT use system Python or `python -m pytest`.

## Critical Coding Rules (Non-Obvious)

- **Always use `source_selector.effective_priority(source, comic, db)`** when comparing source priorities - never read `source.priority` directly in routing logic.
- **Always use `comic.library_title`** (not `comic.title`) in `file_relocator` and `comicinfo_writer` services.
- **Always use `chapter_published_at`** for time-based chapter calculations (not `downloaded_at`).
- **Source selection is per-chapter** - each `ChapterAssignment` has its own `source_id`. Different chapters of the same comic can use different sources.
- **Search results are NOT deduplicated** - duplicates are resolved via `ComicAlias` rows.
- **Hardlinks preferred for file relocation** - use `os.link()` same filesystem, `shutil.copy2()` + `os.replace()` cross-filesystem.
- **Settings loaded via `pydantic_settings.BaseSettings`** from `.env` - use `from app.config import settings` to access.
- **Logger pattern**: `logger = logging.getLogger(f"otaki.{__name__}")` - all modules follow this naming convention.
- **Test fixtures monkeypatch the scheduler** - `scheduler.start`, `scheduler.shutdown`, `scheduler.add_job` are no-ops in unit tests.
- **Integration tests need `.env.test`** file with real Suwayomi credentials - marked with `@pytest.mark.integration`.
