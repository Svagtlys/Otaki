# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

Otaki is a manga/comic request manager built on top of Suwayomi-Server (used only as a download engine). Full design docs: [`CLAUDE.md`](CLAUDE.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/API.md`](docs/API.md).

## Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy async, aiosqlite, APScheduler, Alembic
- **Frontend**: React 18, TypeScript, Vite, Tailwind
- **E2E Tests**: Playwright
- **Package Manager**: pip (backend), npm (frontend)

## Commands

All commands must be run from the `backend/` or `frontend/` directory respectively.

**IMPORTANT: Backend Python commands MUST use the virtual environment at `backend/.venv/`.** Always prefix with `backend/.venv/bin/` (e.g., `backend/.venv/bin/pytest`) or activate the venv first (e.g., `source backend/.venv/bin/activate`).

| Action | Command | Dir |
|--------|---------|-----|
| Run server | `backend/.venv/bin/uvicorn app.main:app --reload` | backend/ |
| Run all tests | `.venv/bin/pytest` | backend/ |
| Run single test | `.venv/bin/pytest tests/test_file.py::test_name -v` | backend/ |
| Run integration tests | `.venv/bin/pytest -m integration` | backend/ |
| Lint Python | `backend/.venv/bin/ruff check .` | backend/ |
| Fix lint | `backend/.venv/bin/ruff check . --fix` | backend/ |
| DB migrations | `backend/.venv/bin/alembic upgrade head` | backend/ |
| Frontend dev | `npm run dev` | frontend/ |
| Frontend build | `npm run build` | frontend/ |
| E2E tests | `npx playwright test` | frontend/ |

> **Note:** `pytest.ini` is inside `backend/`. Always `cd backend` first, or use `-c backend/pytest.ini` from the project root. Running `pytest` without the config file will fail (async mode not detected).

## Critical Non-Obvious Rules (from CLAUDE.md)

- **Source selection is per-chapter** - each `ChapterAssignment` has its own `source_id`. Different chapters of the same comic can come from different sources.
- **Always use `source_selector.effective_priority(source, comic, db)`** - never read `source.priority` directly.
- **Always use `comic.library_title`** (not `comic.title`) in `file_relocator` and `comicinfo_writer`.
- **Always use `chapter_published_at`** for time-based chapter calculations (not `downloaded_at`).
- **Cadence inferred from `chapter_published_at`** with hiatus filtering (>3x median gaps excluded).
- **Two scheduled jobs per comic**: poll (new chapters) and upgrade (better sources) - independent intervals.
- **Search results are NOT deduplicated** - user picks duplicates via `ComicAlias` rows.
- **Suwayomi is staging**; `LIBRARY_PATH` is final library. Hardlinks preferred for relocation.
- **Do NOT mock Suwayomi client in integration tests** - use real running instance.

## Testing

- Tests use in-memory SQLite via [`backend/tests/conftest.py`](backend/tests/conftest.py) fixtures
- Integration tests require `.env.test` with real Suwayomi credentials (marked `@pytest.mark.integration`)
- Fixtures: `db_session` (bare DB), `client` (HTTP), `auth_client` (setup complete), `logged_in_client` (JWT)
- Scheduler is monkeypatched in HTTP test fixtures - real scheduler only in integration tests
