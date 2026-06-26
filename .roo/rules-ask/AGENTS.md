# AGENTS.md - Ask Mode Rules

This file provides documentation context specific to this repository.

## Critical Documentation Context (Non-Obvious)

- **`CLAUDE.md` is the primary design document** - contains non-obvious decisions, data model, roles, and key service responsibilities.
- **`comic.title` vs `comic.library_title`** - `title` is UI display name, `library_title` is used for filesystem paths and ComicInfo.xml. They can differ.
- **Suwayomi is a download engine only** - Otaki owns all orchestration, polling, source selection, and quality decisions. Suwayomi does not auto-discover chapters.
- **Two independent scheduled jobs per comic** - poll job (new chapters) and upgrade job (better sources) with separate configurable intervals.
- **Backend commands run from `backend/` directory** - all pytest, uvicorn, ruff, and alembic commands require `cd backend/` first.
- **Frontend dev server proxies `/api` to `localhost:8000`** - configured in `vite.config.ts`.
