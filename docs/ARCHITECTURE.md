# Architecture

This document is aimed at new contributors. It covers every file in the project, the data model, key workflows, and how the pieces connect.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI (async) |
| Background jobs | APScheduler (in-process, no broker needed) |
| Database | SQLite via SQLAlchemy (ORM + Alembic migrations) |
| Suwayomi client | `gql` async GraphQL client (WebSocket subscriptions) |
| Image processing | OpenCV (`cv2`), Pillow, `imagehash` |
| Frontend | React + Vite, TanStack Query |

The backend is the only process that touches the filesystem or talks to Suwayomi. The frontend is a pure SPA that calls the backend REST API.

---

## High-Level Data Flow

```
User → Frontend → Backend API
                       │
                       ├─ Suwayomi GraphQL API  (queues downloads)
                       │
                       └─ GraphQL subscription  (download events)
                                │
                         chapter_event_handler
                                │
                    ┌───────────┼───────────┐
                    │           │           │
             quality_scanner  upgrade    file_relocator
             image_processor  check
```

Suwayomi's download folder is the **staging area**. Once a chapter is settled (scanned, upgraded if possible), `file_relocator` moves it to the configured **library path**.

---

## Project Layout

```
Otaki/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/
│   │   ├── api/
│   │   ├── services/
│   │   └── workers/
│   ├── watermarks/
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/
│       └── components/
├── docs/
│   └── ARCHITECTURE.md        <- you are here
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Backend Files

### Entry & Config

#### `backend/app/main.py`
FastAPI app entry point. Responsibilities:
- Mount all API routers (`/api/setup`, `/api/auth`, `/api/search`, `/api/requests`, `/api/sources`, `/api/quality`)
- Call `database.init()` on startup (creates tables if not present)
- Start `download_listener` as a background task on startup
- Start APScheduler via `scheduler.start()`

Two middleware functions run on every request (last registered runs first):

1. **`require_setup`** (runs first) — blocks non-exempt routes with 503 until all three settings are configured: `SUWAYOMI_URL`, `SUWAYOMI_DOWNLOAD_PATH`, `LIBRARY_PATH`. Exempt prefix: `/api/setup`, `/api/auth`, `/docs`, `/openapi.json`, `/redoc`.
2. **`require_auth_middleware`** (runs second) — blocks non-exempt routes with 401 if no valid JWT is present in the `Authorization: Bearer` header or `otaki_session` cookie. Validates signature only (no DB lookup). Same exempt prefix as above.

#### `backend/app/config.py`
Reads `.env` using Pydantic `BaseSettings`. Exposes a singleton `settings` object used everywhere else. Fields: `SUWAYOMI_URL`, `SUWAYOMI_USERNAME`, `SUWAYOMI_PASSWORD`, `SUWAYOMI_DOWNLOAD_PATH`, `LIBRARY_PATH`, `CHAPTER_NAMING_FORMAT`, `WATERMARKS_PATH`, `COVERS_PATH`, `AUTO_FIX_BANNERS`, `DOWNLOAD_POLL_FALLBACK_SECONDS`, `MAX_RECONNECT_ATTEMPTS`. All fields are optional at startup — if `SUWAYOMI_URL` is unset, the app serves the setup wizard instead of the normal UI.

#### `backend/app/database.py`
SQLAlchemy `AsyncEngine` + `AsyncSession` setup. Exports:
- `init()` — creates all tables
- `get_db` — FastAPI dependency that yields a session per request

---

### Models

#### `backend/app/models/comic.py`
`Comic` — one row per tracked title. Source is tracked per chapter (via `ChapterAssignment`), not per comic.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `title` | str | Display name in Otaki UI |
| `library_title` | str | Canonical name used for folder path and `ComicInfo.xml` `<Series>` tag; set at request time, defaults to `primary_title` |
| `cover_path` | str \| null | Path to stored cover image under `COVERS_PATH`; `null` if no cover set |
| `status` | enum | `tracking` / `complete` |
| `inferred_cadence_days` | float \| null | Median days between recent chapters, recalculated after each poll |
| `poll_override_days` | int \| null | User override for new-chapter poll interval; `null` = use inferred |
| `upgrade_override_days` | int \| null | User override for upgrade check interval; `null` = use inferred |
| `next_poll_at` | datetime \| null | When Otaki will next poll for new chapters |
| `next_upgrade_check_at` | datetime \| null | When Otaki will next run upgrade checks |
| `last_upgrade_check_at` | datetime \| null | When upgrade checks last ran |
| `created_at` | datetime | |

#### `backend/app/models/source.py`
`Source` — user's ranked list of Suwayomi extensions.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `suwayomi_source_id` | str | Suwayomi's source ID string |
| `name` | str | Human-readable label |
| `priority` | int | 1 = best/most preferred |
| `enabled` | bool | |
| `created_at` | datetime | |

#### `backend/app/models/chapter_assignment.py`
`ChapterAssignment` — tracks which source each chapter was downloaded from. Multiple rows per chapter during an upgrade; only one has `is_active=true` at any time.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `comic_id` | int FK → comics | |
| `chapter_number` | float | e.g. 12.5 for half-chapters |
| `volume_number` | int nullable | |
| `source_id` | int FK → sources | |
| `suwayomi_manga_id` | str | May differ from comic's current ID during upgrade |
| `suwayomi_chapter_id` | str | |
| `download_status` | enum | `queued` / `downloading` / `done` / `failed` |
| `is_active` | bool | True for the canonical copy |
| `chapter_published_at` | datetime | `uploadDate` from Suwayomi source metadata — used for cadence inference |
| `downloaded_at` | datetime nullable | |
| `library_path` | str nullable | Absolute path in `LIBRARY_PATH` after relocation |
| `relocation_status` | enum | `pending` / `done` / `failed` / `skipped` |

#### `backend/app/models/quality_scan.py`
Two tables:

**`QualityScan`** — result of scanning one chapter.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `chapter_assignment_id` | int FK | |
| `scanned_at` | datetime | |
| `watermark_count` | int | |
| `watermark_templates_matched` | JSON | List of `watermark_template.id` |
| `has_header` | bool | |
| `has_footer` | bool | |
| `severity` | enum | `clean` / `minor` / `moderate` / `severe` |
| `auto_fixed` | bool | Whether image_processor ran |

**`User`** — Otaki user account.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `username` | str | |
| `email` | str | |
| `password_hash` | str \| null | Null for SSO-only accounts |
| `sso_provider` | str \| null | e.g. `"google"`, `"github"`, or OIDC issuer URL |
| `sso_sub` | str \| null | Provider's subject identifier |
| `role` | enum | `reader` / `requestor` / `admin` |
| `created_at` | datetime | |

**`ComicAlias`** — all known titles for a comic. Searched when polling sources for new chapters.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `comic_id` | int FK → comics | |
| `title` | str | Title as known on this source |
| `source_id` | int FK nullable | Which source uses this title; `null` = applies to all |

**`ComicSourceOverride`** — per-comic source priority overrides, takes precedence over global source priority for that comic.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `comic_id` | int FK → comics | |
| `source_id` | int FK → sources | |
| `priority_override` | int | Lower = more preferred; replaces global priority for this comic |

**`WatermarkTemplate`** — metadata for a saved template image.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | str | |
| `source_id` | int FK nullable | Which source this watermark belongs to |
| `file_path` | str | Relative to `WATERMARKS_PATH` |
| `match_threshold` | float | 0.0–1.0; default 0.8 |
| `enabled` | bool | |

---

### API Routers

#### `backend/app/api/auth.py`
Authentication endpoints. Sessions are JWT-based (HS256, 24h expiry). Crypto helpers live in `services/auth.py`.

- `POST /api/auth/login` — accepts `{username, password}`, validates against `users` table, returns `{access_token, token_type}`
- `POST /api/auth/logout` — 200 no-op; client discards the token (stateless JWT)
- `GET /api/auth/me` — reads `Authorization: Bearer <token>`, returns `{id, username}`

**`require_auth` dependency** — validates JWT and injects the active `User` into route handlers. Accepts token from `Authorization: Bearer` header or `otaki_session` cookie. Raises 401 on missing, invalid, or expired tokens. Use as `user: User = Depends(require_auth)`.

**Not yet implemented (future issues):**
- `GET /api/auth/callback` — OAuth2/OIDC redirect handler (#future)
- Role-based `require_permission` dependency — post-MVP

#### `backend/app/services/auth.py`
Shared bcrypt + JWT helpers used by both `setup.py` and `auth.py`.

- `hash_password(password)` — bcrypt hash
- `verify_password(plain, hashed)` — constant-time bcrypt compare
- `create_token(user_id)` — encodes `{sub, exp}` as signed JWT
- `decode_token(token)` — decodes and verifies; raises `jwt.InvalidTokenError` on failure

#### `backend/app/api/setup.py`
First-time setup wizard endpoints. Steps 2–5 are guarded by `require_setup_incomplete` (409 once all three settings are set). `POST /api/setup/user` has no such guard — user creation is allowed at any time. Wizard step order:

1. `POST /api/setup/user` — creates the first admin user; 409 if any user already exists
2. `POST /api/setup/connect` — accepts `{url, username, password}`, calls `suwayomi.ping()`, saves credentials to config
3. `GET /api/setup/sources` — calls `suwayomi.list_sources()` and returns installed sources for priority ordering
4. `POST /api/setup/sources` — accepts an ordered list of source IDs, creates `Source` rows with assigned priorities
5. `POST /api/setup/paths` — accepts `{download_path, library_path}`, validates both paths exist, saves to config

#### `backend/app/api/search.py`
`GET /api/search?q=<title>`

Fans out to all enabled sources via `suwayomi.search_source()` in parallel. Returns all results without deduplication, including `source_id` and `source_name` per result so the frontend can show which source each card came from. The user selects which results belong to the same series at request time.

#### `backend/app/api/requests.py`
CRUD for tracked comics.

- `POST /api/requests` — creates a `Comic`, calls `source_selector.build_chapter_source_map()`, adds manga to Suwayomi per source, enqueues downloads, creates `ChapterAssignment` rows, registers APScheduler jobs for poll and upgrade
- `GET /api/requests` — list with download status and worst quality severity
- `GET /api/requests/{id}` — full detail: chapters, quality badges, library paths
- `DELETE /api/requests/{id}` — remove tracking; optionally removes library files and Suwayomi entry

#### `backend/app/api/sources.py`
- `GET/POST/PATCH/DELETE /api/sources` — source priority list CRUD
- `POST /api/sources/watermarks` — accepts a multipart upload (image file + `x, y, w, h, name, source_id`) and calls `template_extractor.extract_template()`
- `GET/DELETE /api/sources/watermarks/{id}` — list and remove templates

#### `backend/app/api/quality.py`
- `GET /api/quality/{comic_id}` — per-chapter scan results
- `POST /api/quality/{assignment_id}/rescan` — re-runs `quality_scanner.scan_chapter()` on the existing CBZ
- `POST /api/quality/{assignment_id}/autofix` — manually runs `image_processor.crop_chapter()`
- `POST /api/quality/{assignment_id}/relocate` — manually re-triggers relocation

---

### Services

#### `backend/app/services/suwayomi.py`
Async GraphQL client. All Suwayomi communication goes through here — nothing else should import `gql` directly. All Suwayomi operations that fetch remote data use GraphQL mutations (Suwayomi triggers a live fetch), not queries.

Implemented:
- `ping(url, username, password)` → bool — verifies connectivity; used by setup wizard
- `list_sources()` → `list[{id, name, lang, icon_url}]` — installed sources; used by setup wizard
- `search_source(source_id, query)` → `list[{manga_id, title, cover_url, synopsis, url}]` — searches a single source by title string; `manga_id` is a string; `cover_url`, `synopsis`, and `url` may be null
- `fetch_chapters(manga_id)` → `list[{chapter_number, volume_number, suwayomi_chapter_id, chapter_published_at}]` — fetches all chapters for a manga from Suwayomi. `uploadDate` is a ms-epoch string; converted to `datetime` (UTC). `volume_number` is always `None` (not exposed by Suwayomi's chapter API).
- `enqueue_downloads(chapter_ids)` → void — enqueues a list of chapter IDs for download via `enqueueChapterDownloads` mutation.
- `subscribe_download_changed()` → async generator of `(chapter_id, chapter_name, manga_title, source_display_name)` tuples — maintains a `graphql-transport-ws` WebSocket subscription to Suwayomi's `downloadStatusChanged(input: DownloadChangedInput!)` subscription. Yields one tuple per `FINISHED` event (checked via `DownloadUpdate.type`). On the first event, also yields any entries in the `initial` field (chapters already `FINISHED` in the queue at connect time).
- `poll_downloads()` → `list[tuple]` — REST fallback used when the WebSocket subscription is unavailable. Polls `GET /api/v1/downloads` and returns the same tuple format as `subscribe_download_changed`.

Not yet implemented:
- `add_to_library(source_id, manga_url)` → Suwayomi manga ID
- `delete_manga(manga_id)` → void

#### `backend/app/services/source_selector.py`
Per-chapter source selection logic. Stateless — takes a DB session as argument.

- `effective_priority(source, comic, db) → int` — async; returns `source.priority` for MVP. Stubbed as `async def` so callers need no changes when 1.3 adds `ComicSourceOverride` lookup.
- `build_chapter_source_map(comic, db)` → `dict[float, tuple[Source, str]]` — fans out to all enabled sources in parallel using `comic.title` (alias lookup deferred to 1.1). For each source: searches for the title, then fetches chapters. Returns `{chapter_number: (best_source, suwayomi_manga_id)}`. `suwayomi_manga_id` is bundled in the return value so callers don't need a second lookup. Sources that error during fetch are skipped with a warning log. Uses `asyncio.gather` with `return_exceptions=False` per source coroutine.
- `find_upgrade_candidates(comic, db)` → `list[tuple[ChapterAssignment, Source]]` — loads active assignments (with source eager-loaded), calls `build_chapter_source_map`, returns pairs where a better-priority source now has the chapter.

#### `backend/app/services/cadence_inferrer.py`
Infers release cadence from chapter history.

- `infer_cadence(comic, db) → float | None` — queries `chapter_published_at` (not `downloaded_at`) from the N most recent `ChapterAssignment` rows for the comic and computes the median inter-chapter gap in days. Using source publication dates means bulk-downloading a back-catalogue produces a sensible cadence immediately, rather than clustering all gaps near zero. Hiatus-aware: gaps more than 3× the initial median are excluded before the final median is computed. Returns `None` if fewer than 2 chapters exist. Called at request time (to initialise `next_poll_at`/`next_upgrade_check_at`) and after each poll job when new chapters are found.

#### `backend/app/services/quality_scanner.py`
Image quality analysis. Does **not** modify files.

- `scan_chapter(cbz_path) → ScanResult` — opens CBZ, extracts first and last images only (banners only appear there). For each: runs `cv2.matchTemplate` against all enabled templates; computes pHash of top/bottom 80px and compares against known banner hashes.
- `compute_severity(scan_result) → Severity` — `clean` if no matches; `minor` for isolated watermarks; `moderate` for watermarks or single banner; `severe` for both.

Watermark templates are loaded once at startup and cached in memory.

#### `backend/app/services/cover_injector.py`
Manages per-comic cover images and injects them into chapter CBZ archives.

- `save_from_url(comic_id, url) → Path` — downloads the image at `url` and saves it to `COVERS_PATH/{comic_id}.{ext}`. Returns the saved path.
- `save_from_upload(comic_id, image_bytes, content_type) → Path` — saves a user-uploaded image to `COVERS_PATH/{comic_id}.{ext}`. Existing cover is replaced.
- `inject(cbz_path, comic)` — if `comic.cover_path` is set, opens the CBZ and adds (or replaces) an entry named `cover.png` at the beginning of the archive. No-op if `comic.cover_path` is null.

#### `backend/app/services/comicinfo_writer.py`
Writes or updates `ComicInfo.xml` inside a CBZ archive, ensuring all chapters of a comic report the same series name to comic library software (Komga, Kavita, etc.).

- `write(cbz_path, comic, assignment)` — opens the CBZ, reads existing `ComicInfo.xml` if present, sets `<Series>` to `comic.library_title`, `<Number>` to `assignment.chapter_number`, and `<Volume>` to `assignment.volume_number` (if set). Repacks the CBZ in-place. Called after quality scan / auto-fix and before relocation.

Fields written to `ComicInfo.xml`:

| Field | Value |
|---|---|
| `<Series>` | `comic.library_title` |
| `<Number>` | `assignment.chapter_number` |
| `<Volume>` | `assignment.volume_number` (omitted if null) |

Any other existing fields are preserved unchanged.

#### `backend/app/services/template_extractor.py`
Creates templates from user-supplied pages.

- `extract_template(image_bytes, x, y, w, h, name, source_id, db) → WatermarkTemplate` — crops the region using Pillow, saves as PNG to `WATERMARKS_PATH/{name}.png`, inserts a `WatermarkTemplate` row, invalidates the in-memory template cache in `quality_scanner`.

#### `backend/app/services/image_processor.py`
Modifies CBZ files to remove banners. **Mutates files** — always backs up first.

- `crop_chapter(cbz_path, scan_result)` — renames original to `*.cbz.orig`, re-packs CBZ with first page top-cropped and/or last page bottom-cropped at the boundary detected by `scan_result`. Boundary detection uses pixel-row variance: the first row with high variance after the uniform banner region.

#### `backend/app/services/file_relocator.py`
Moves settled chapters from Suwayomi's staging folder to the final library. Radarr/Sonarr-style.

- `resolve_path(assignment, comic) → Path` — renders `CHAPTER_NAMING_FORMAT` with tokens `{title}` (uses `comic.library_title`), `{chapter}` (zero-padded float), `{volume}` (optional), `{year}`, `{source}`. Returns absolute path under `LIBRARY_PATH`.
- `relocate(assignment, comic, db)` — resolves destination, creates parent dirs, then:
  - **Same filesystem**: `os.link()` (hardlink — instant, no extra disk space)
  - **Different filesystem**: `shutil.copy2()` to temp path, verify size, then `os.replace()`, delete staging copy
  - Updates `assignment.library_path` and `assignment.relocation_status=done`
- `replace_in_library(old_assignment, new_assignment, comic, db)` — used during upgrades when `old_assignment.library_path` is set. Writes new file to a temp path alongside the existing library file, then `os.replace()` for atomic swap. No window where the file is missing.

---

### Workers

#### `backend/app/workers/scheduler.py`
<<<<<<< feat/download-listener
Initialises APScheduler with an `AsyncIOScheduler`. On startup, registers two jobs per tracked comic: a **poll job** (fires at `next_poll_at`, interval = `poll_override_days` or `inferred_cadence_days`) and an **upgrade job** (fires at `next_upgrade_check_at`, interval = `upgrade_override_days` or `inferred_cadence_days`). When a new comic is requested via the API, both jobs are registered immediately.
=======
Initialises APScheduler with an `AsyncIOScheduler` module-level singleton. All jobs use the `date` trigger — each job re-schedules itself when it finishes, advancing `next_poll_at` by the poll interval (hardcoded 7-day MVP fallback; cadence inference deferred to #16).

Public API:

- `start(db: AsyncSession) → None` — loads all comics with `status=tracking`, registers a poll job for each via `_register_poll_job`, then calls `scheduler.start()`. Called from `main.py` lifespan on startup.
- `register_comic_jobs(comic: Comic) → None` — registers jobs for a newly created comic. Called by `POST /api/requests` (#13) after committing the new `Comic` row.

Internal:

- `_register_poll_job(comic)` — calls `scheduler.add_job` with `trigger="date"`, `run_date=comic.next_poll_at` (or `now(UTC)` if unset), `id=f"poll_{comic.id}"`, `replace_existing=True`.
- `_poll_comic(comic_id)` — opens a fresh `AsyncSessionLocal` session. Loads the comic; returns early if not found or `status=complete`. Calls `build_chapter_source_map`, compares against existing active `ChapterAssignment` chapter numbers, groups new chapters by `(source_id, suwayomi_manga_id)`, calls `fetch_chapters` per group, creates `ChapterAssignment` rows (`download_status=queued`, `is_active=True`, `chapter_published_at` from fetch result), calls `enqueue_downloads`, advances `comic.next_poll_at`, re-registers the job, and commits.

Upgrade job deferred to #19 — no stub present.
>>>>>>> develop

#### `backend/app/workers/download_listener.py`
Maintains a persistent WebSocket connection to Suwayomi's `downloadStatusChanged` GraphQL subscription. On each `FINISHED` event (via `DownloadUpdate.type`), dispatches to `chapter_event_handler.handle(chapter_id, chapter_name, manga_title, source_display_name)` as a non-blocking `asyncio.create_task()` so slow relocations don't block the listener.

State machine:
- **SUBSCRIPTION mode** (default): connect via `subscribe_download_changed()`; on error, retry with exponential backoff (2s, 4s, 8s… capped at 30s). After `MAX_RECONNECT_ATTEMPTS` consecutive failures, switch to POLLING mode.
- **POLLING mode** (fallback): call `poll_downloads()` every `DOWNLOAD_POLL_FALLBACK_SECONDS`. On first success, switch back to SUBSCRIPTION mode.

Started by `main.py` lifespan as `asyncio.create_task(download_listener.run())` and cancelled on shutdown. Runs for the lifetime of the process regardless of whether Otaki has active downloads — unrecognised chapter IDs (downloads not initiated by Otaki) are silently ignored in `chapter_event_handler`.

#### `backend/app/workers/chapter_event_handler.py`
Orchestrates relocation for every completed chapter download. Does not drive upgrade or
poll scheduling — those are APScheduler jobs.

```
handle(suwayomi_chapter_id, chapter_name, manga_title, source_display_name)
  1. Load ChapterAssignment by suwayomi_chapter_id (warn + return if not found)
  2. Set download_status=done, downloaded_at=now(UTC)
  3. [deferred 1.4] scan     → quality_scanner.scan_chapter()
  4. [deferred 1.4] write    → QualityScan row
  5. [deferred 1.4] fix      → image_processor.crop_chapter() (if AUTO_FIX_BANNERS)
  6. [deferred 1.1] comicinfo → comicinfo_writer.write()
  7. [deferred 1.1] cover    → cover_injector.inject()
  8. Check for upgrade: query for existing active ChapterAssignment with same
     comic_id + chapter_number but different id
     - None found → regular download: file_relocator.relocate(), set is_active=True
     - Found      → upgrade download: file_relocator.replace_in_library(old, new),
                    set old.is_active=False, new.is_active=True

on upgrade download (1.0): always swap — no quality condition until scanner added in 1.4
on upgrade download (1.4+): swap only if new severity ≤ old severity
```

---

## Frontend Pages

#### `frontend/src/pages/Search.tsx`
Search bar → `GET /api/search`. Results as cards (cover, title, synopsis). "Request" button → `POST /api/requests`. Optimistic UI with loading/success/error states.

#### `frontend/src/pages/Library.tsx`
All tracked comics. Columns: cover, title, source, worst severity badge, download progress, next update time. Row click → Comic detail.

#### `frontend/src/pages/Comic.tsx`
Chapter-level detail. Table: chapter number, source, download status, severity badge, library path, re-scan button, force-upgrade button. Severity badge tooltips show which templates matched and banner flags.

#### `frontend/src/pages/Sources.tsx`
Two panels:
- **Source priority** — drag-to-reorder list of sources. Each row: source name, priority number, enabled toggle, aggregate quality stats (% clean chapters from this source).
- **Watermark templates** — list with name, source, threshold. "Add template": image upload + canvas crop selector to define the watermark region.

---

## Key Design Decisions

**Why is Suwayomi's folder the staging area?**
Suwayomi manages its own file structure and needs its copies to serve pages and track download state. We treat it as staging and own the final library separately so Suwayomi can be upgraded/reset without losing the library.

**Why hardlinks for relocation?**
When staging and library are on the same filesystem (the common Docker volume case), a hardlink costs no extra disk space and is instant. The file isn't actually duplicated — both paths point to the same inode. Deleting the staging copy later just removes one reference.

**Why only scan first and last pages?**
Group scan banners (headers/footers) appear once per chapter — on the first or last page of the CBZ. Scanning every page would be wasteful. Watermarks that appear on inner pages would be from a different pattern (e.g. per-page semi-transparent overlays) and are not in scope for the current detection approach.

**Why does Otaki drive polling instead of Suwayomi?**
Suwayomi tracks a manga against a single source. If we let Suwayomi poll, it only checks that one source — a new chapter on a lower-priority source would be missed until that source catches up. By having Otaki poll all sources and pick the best available, the correct source is chosen at download time and upgrades are scoped to chapters that genuinely have a better option.

**Why separate poll and upgrade intervals?**
A series might release weekly but a lower-quality source that you want to upgrade away from could take months to be picked up by a better source. Separating the intervals lets you poll aggressively for new chapters while checking upgrades less frequently to avoid wasted API calls.
