# Otaki — Comic Request Manager

## Context
A personal comic/manga request manager that sits on top of a running Suwayomi-Server instance. Users search for titles, submit download requests, and the app handles source selection, quality checking, and automatic source upgrades. Suwayomi is used only as a download engine (via its GraphQL API); our app owns orchestration logic and image processing directly on the shared filesystem.

---

## Viability Assessment

**Feasible.** The hard parts are:
- **Source routing**: Suwayomi treats each source as a separate manga entry. To "switch sources" we must add the same manga from a different source, re-download, then clean up the old one.
- **Quality detection accuracy**: Template matching works well for extracted watermark templates; banner detection on first/last page is reliable for recurring headers/footers.
- **Filesystem coupling**: Image processing and relocation require that our app and Suwayomi share the same download path (volume mount in Docker or same host).
- **Update event detection**: Otaki drives new chapter polling itself across all sources; Suwayomi's GraphQL subscription is used only to receive download-complete events, not to detect new chapters.
- **Relocation timing**: A chapter should only be relocated to the final library once it is "settled" — quality checked, auto-fixed if needed, and no upgrade pending. During upgrades the old library file must be atomically replaced.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | Python + FastAPI | Best image processing ecosystem (OpenCV, Pillow, imagehash); async support |
| Background jobs | APScheduler (in-process) | Simple, no extra broker needed for this scale |
| Database | SQLite via SQLAlchemy | Zero-config, plenty for personal use |
| Frontend | React + Vite + TanStack Query | Fast dev, simple SPA, no SSR needed |
| Suwayomi client | `gql` (Python async GraphQL client) | Matches Suwayomi's GraphQL-first API; supports subscriptions |
| Image processing | OpenCV + Pillow + imagehash | Template matching, cropping, perceptual hashing |

---

## Project Structure

```
Otaki/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app entry
│   │   ├── config.py             # Suwayomi URL, paths, env vars
│   │   ├── database.py           # SQLAlchemy setup
│   │   ├── models/               # DB models
│   │   │   ├── comic.py
│   │   │   ├── source.py
│   │   │   ├── chapter_assignment.py
│   │   │   ├── quality_scan.py
│   │   │   ├── user.py
│   │   │   └── comic_source_override.py
│   │   ├── api/                  # FastAPI routers
│   │   │   ├── auth.py           # Login, logout, OAuth2 callback, session tokens
│   │   │   ├── setup.py          # First-run setup wizard endpoints
│   │   │   ├── search.py         # Search across sources, merge results
│   │   │   ├── requests.py       # CRUD for tracked comics
│   │   │   ├── sources.py        # Source priority config + watermark management
│   │   │   └── quality.py        # Scan results per comic/chapter
│   │   ├── services/
│   │   │   ├── suwayomi.py       # GraphQL client wrapper
│   │   │   ├── source_router.py  # Priority selection logic
│   │   │   ├── cadence_inferrer.py   # Infer release cadence from chapter history
│   │   │   ├── quality_scanner.py# Watermark + banner detection
│   │   │   ├── template_extractor.py # Extract watermark templates from sample images
│   │   │   ├── image_processor.py# Crop/remove banners from pages
│   │   │   ├── comicinfo_writer.py   # Write/update ComicInfo.xml inside CBZ
│   │   │   ├── cover_injector.py     # Inject cover.png into each chapter CBZ
│   │   │   └── file_relocator.py # Move settled chapters to final library path
│   │   └── workers/
│   │       ├── scheduler.py           # APScheduler setup
│   │       ├── download_listener.py   # GraphQL subscription for download events
│   │       └── chapter_event_handler.py # Quality + relocation logic per chapter
│   ├── watermarks/               # Extracted watermark template images (cropped)
│   ├── covers/                   # Per-comic cover images (one file per comic)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Login.tsx         # Local + SSO login
│   │   │   ├── Search.tsx        # Search + request submission
│   │   │   ├── Library.tsx       # All tracked comics + status
│   │   │   ├── Comic.tsx         # Per-comic: chapters, quality scores, next update
│   │   │   ├── Sources.tsx       # Source priority + watermark template management
│   │   │   ├── Settings.tsx      # Suwayomi config, paths, SSO config (admin)
│   │   │   └── Users.tsx         # User management (admin only)
│   │   └── components/
│   └── package.json
├── docs/
│   └── ARCHITECTURE.md           # Developer guide — file reference, workflows, design decisions
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Database Schema

### `sources`
Priority-ranked list of Suwayomi sources/extensions.
```
id, suwayomi_source_id, name, priority (int, 1=best), enabled, created_at
```

### `comics`
Each tracked title (one row per title). Source is tracked per chapter, not per comic.
```
id, title (display name in Otaki UI),
library_title (canonical name used for folder path and ComicInfo.xml Series tag),
cover_path (str nullable — path to stored cover image under COVERS_PATH),
status (tracking|complete),
inferred_cadence_days (float nullable — median days between chapters, computed from history),
poll_override_days (int nullable — user override for new-chapter polling interval),
upgrade_override_days (int nullable — user override for upgrade check interval),
next_poll_at (datetime nullable — when Otaki will next check for new chapters),
next_upgrade_check_at (datetime nullable — when Otaki will next check for source upgrades),
last_upgrade_check_at (datetime nullable), created_at
```

### `chapter_assignments`
Which source each chapter was downloaded from. Multiple rows per chapter during upgrades.
```
id, comic_id (FK), chapter_number, volume_number (nullable), source_id (FK),
suwayomi_manga_id, suwayomi_chapter_id,
download_status (queued|downloading|done|failed), is_active (bool),
chapter_published_at (datetime — uploadDate from Suwayomi source metadata),
downloaded_at (datetime nullable),
library_path (nullable — absolute path in final library, set after relocation),
relocation_status (pending|done|failed|skipped)
```

### `quality_scans`
Results of quality checks per chapter.
```
id, chapter_assignment_id (FK), scanned_at,
watermark_count (int), watermark_templates_matched (json list of template ids),
has_header (bool), has_footer (bool),
severity (enum: clean|minor|moderate|severe), auto_fixed (bool)
```

### `watermark_templates`
Extracted template images used for matching.
```
id, name, source_id (FK, nullable — which source this watermark belongs to),
file_path (relative to watermarks/), match_threshold (float, 0-1), enabled
```

### `users`
Otaki user accounts, supporting both local credentials and SSO.
```
id, username, email,
password_hash (nullable — null for SSO-only accounts),
sso_provider (nullable — eg "google", "github", or custom OIDC issuer),
sso_sub (nullable — provider's subject identifier),
role (enum: reader|requestor|admin),
created_at
```

### `comic_aliases`
All known titles for a comic across sources. Used when searching sources for chapters so that alternate titles (different languages, transliterations, regional names) are all checked.
```
id, comic_id (FK), title, source_id (FK nullable — which source uses this title)
```

### `comic_source_overrides`
Per-comic source priority overrides. When present, these take precedence over global source priority for that comic only.
```
id, comic_id (FK), source_id (FK), priority_override (int — lower = more preferred)
```

---

## Key Workflows

### A. Request Flow
1. User types title → frontend calls `/api/search?q=...`
2. Backend queries all enabled Suwayomi sources in parallel; results are **not deduplicated** — the same series may appear with different titles across sources (e.g. "One Piece" on one source, "ワンピース" on another)
3. Each result card shows the title, cover image, and source name
4. User selects one or more result cards that represent the same series; sets a preferred display name (`primary_title`) and `library_title`
5. User picks a cover from the available cover images across the selected results, or uploads their own
6. User clicks "Request"
7. Backend creates a `Comic` row (`title = primary_title`), downloads and stores the chosen cover to `COVERS_PATH/{comic_id}.{ext}`, and creates one `ComicAlias` row per selected result
7. `source_router.build_chapter_source_map()` searches all sources using all known aliases, building a per-chapter availability map:
   - For each chapter, pick the **highest-priority source that has it**
   - Chapters on different sources are expected and handled naturally
8. For each distinct source needed, call Suwayomi `addMangaToLibrary` + `fetchChapterList`
9. Call `enqueueChapterDownloads` grouped by source
10. Create one `ChapterAssignment` row per chapter with the selected source
11. `download_listener` watches for download events for all active Suwayomi manga IDs for this comic

### B. Download Listener + Quality Check
1. `download_listener` maintains a persistent GraphQL subscription to Suwayomi's `downloadChanged` events
2. On chapter `DOWNLOADED`:
   - Locate CBZ archive on shared filesystem
   - Run `quality_scanner.scan_chapter(cbz_path)`:
     - Open CBZ, extract **first and last images only** (banners appear only there)
     - For first image: run `cv2.matchTemplate` against all enabled templates; check top of image for banner pattern (phash of top N rows vs known banner hashes)
     - For last image: same watermark check; check bottom for footer banner
   - Compute `severity`:
     - `clean` — no matches
     - `minor` — 1 watermark, no banners
     - `moderate` — watermarks or banner on one end
     - `severe` — watermarks + banners both ends
3. Write `quality_scan` row to DB
4. If banners detected and auto-fix enabled: `image_processor.crop_chapter(cbz_path, scan_result)` — crops first/last pages in-place, keeps `.orig` backup
5. `comicinfo_writer.write(cbz_path, comic, assignment)` — updates or creates `ComicInfo.xml` inside the CBZ with the canonical `library_title` as `<Series>`, ensuring all chapters report the same series name regardless of source
6. `cover_injector.inject(cbz_path, comic)` — if `comic.cover_path` is set, adds the cover image to the CBZ as `cover.png` (replaces any existing entry of that name)
7. Relocate settled chapter (see F)

### C. Upgrade Checks (scheduled)
Upgrades run on a per-comic APScheduler job. The interval used is `upgrade_override_days` if set, otherwise `inferred_cadence_days`. The job fires at `next_upgrade_check_at` and advances that timestamp after each run.

**Upgrade check logic:**
1. For each chapter of the comic with `is_active=true` not already on the best possible source, query each higher-priority source via `suwayomi.fetch_chapters()` to check availability
2. For each chapter where a better source is available:
   - Add manga from that source to Suwayomi library if not already there
   - Enqueue chapter download
   - On download complete: run quality scan
   - If new severity ≤ old severity: swap (`is_active` flip, atomic library replace if already relocated)
   - Otherwise: keep old assignment, discard new one
3. Update `comic.last_upgrade_check_at` and advance `comic.next_upgrade_check_at`

### D. New Chapter Polling (Otaki-driven)
Otaki polls for new chapters itself rather than relying on Suwayomi's internal scheduler. This ensures chapter detection always checks all sources and assigns the best available one.

**Poll interval:** `poll_override_days` if set, otherwise `inferred_cadence_days`. APScheduler fires the job at `next_poll_at` per comic.

**Poll job logic:**
1. For each enabled source (priority order), call `suwayomi.fetch_chapters()` to get the current chapter list
2. Compare against known `ChapterAssignment` rows — any chapter number not in DB is new
3. For each new chapter: pick the highest-priority source that has it, add to Suwayomi library if needed, enqueue download
4. Advance `comic.next_poll_at` by the effective interval
5. Recalculate `inferred_cadence_days` from updated chapter timestamps (see Cadence inference below)

**Cadence inference:**
- Uses `chapter_published_at` (sourced from Suwayomi's `uploadDate` per chapter) — not `downloaded_at`, which clusters at bulk download time and is meaningless for cadence
- Compute all inter-chapter gaps from `chapter_published_at` of the last N chapters
- Hiatus filtering: compute an initial median, then discard any gaps more than 3× that value (hiatuses, long breaks) before computing the final median
- Store result in `comic.inferred_cadence_days`; drives both poll and upgrade intervals unless overridden
- **Computed at request time** using existing chapter publication dates — so a user adding an ongoing series with 200 back-chapters gets a sensible cadence immediately
- Recalculated after each poll job when new chapters are found
- On first request with no chapter history (brand new series, 0 chapters): default to 7 days

### E. Watermark Template Creation
The user has pages that contain watermarks but no clean template images.
1. In Sources settings UI: user uploads a sample page containing the watermark
2. User draws a bounding box over the watermark region in the UI (simple image crop selector)
3. Backend receives the crop coordinates + image, uses Pillow to extract that region, saves as a template in `watermarks/`
4. Creates `watermark_templates` DB row with name, source association, and default threshold
5. Template is immediately available for future scans; user can re-scan existing chapters

### F. File Relocation (Radarr/Sonarr-style)
Triggered once a chapter is settled (quality checked + no upgrade pending).
1. `file_relocator.resolve_path(assignment, comic)` renders the final destination path using the configured naming format:
   - Token examples: `{title}`, `{chapter}` (zero-padded), `{volume}` (optional), `{year}`, `{source}`
   - Default format: `{title}/{title} - Ch.{chapter:04.1f}.cbz`
   - Volume-aware format: `{title}/Vol.{volume:02d} Ch.{chapter:04.1f}.cbz`
2. Create destination directory if needed
3. Transfer strategy (determined at runtime):
   - **Same filesystem** → hardlink (zero cost, instant; staging and library share the file)
   - **Different filesystem** → copy to destination, then delete staging copy after verification
4. Update `chapter_assignment.library_path` and set `relocation_status=done`
5. Display final library path in UI per chapter

**Changing `library_title` after relocation**: if the user renames the library title after chapters are already relocated, `file_relocator` must move all existing library files to the new path. This is handled as an explicit PATCH operation — Otaki renames the folder atomically. Flag as a known complexity; see TODO.

**During source upgrades** (when a settled chapter is being replaced):
- New file is placed in staging as usual
- After upgrade quality check passes: perform atomic replace — write new file to temp path alongside old library file, then `os.replace()` (atomic on POSIX) to swap in place
- This avoids a window where the library file is missing

---

## Quality Feedback in UI

Per-comic view shows a quality summary table per chapter:
- Color-coded severity badge per chapter (green=clean, yellow=minor, orange=moderate, red=severe)
- Tooltip shows: watermark count, which templates matched, banner presence
- Comic-level aggregate: worst severity seen, % of chapters clean
- Source priority view shows aggregate quality scores per source to help users tune priorities

---

## Quality Detection Approach

**Watermarks (extracted templates)**
- Load all enabled `watermark_templates` at startup
- `cv2.matchTemplate(page_gray, template_gray, cv2.TM_CCOEFF_NORMED)` on first and last pages
- If `max_val ≥ match_threshold` → watermark detected; record bounding box

**Headers/Footers (banners on first/last page)**
- Slice top 80px of first page, bottom 80px of last page
- Compute `imagehash.phash()` for each slice
- Compare against phashes of known banner images stored alongside templates
- Hamming distance ≤ 10 → banner match
- For removal: detect pixel-row boundary (row where variance increases significantly = content begins)

**Auto-removal**
- Crop affected edges using Pillow: `img.crop((0, header_h, w, h - footer_h))`
- Re-pack into CBZ; keep original CBZ as `filename.cbz.orig`

---

## Suwayomi API Integration Points

All via GraphQL POST/subscription to `{SUWAYOMI_URL}/api/graphql`:

| Operation | When Used |
|---|---|
| Search/browse source manga | Deduplicated search across sources |
| `addMangaToLibrary` mutation | When request is submitted or upgrade begins |
| `fetchChapterList` mutation | After adding to library |
| `enqueueChapterDownloads` mutation | Triggering downloads |
| `downloadChanged` subscription | Real-time download events (drives quality + upgrade) |
| Chapter list query per source | Poll job: detect new chapters across all sources |
| Delete/remove manga mutation | Cleanup after source upgrade |

---

## Configuration (.env)
All fields are optional at startup. If `SUWAYOMI_URL` is absent, the frontend serves the setup wizard instead of the normal UI. The setup wizard writes these values once complete.
```
SUWAYOMI_URL=http://localhost:4567
SUWAYOMI_USERNAME=                                   # optional, if Suwayomi auth is enabled
SUWAYOMI_PASSWORD=                                   # optional, if Suwayomi auth is enabled
SUWAYOMI_DOWNLOAD_PATH=/path/to/suwayomi/downloads   # staging area
LIBRARY_PATH=/path/to/final/library                  # final destination
CHAPTER_NAMING_FORMAT={title}/{title} - Ch.{chapter:04.1f}.cbz
WATERMARKS_PATH=./backend/watermarks
COVERS_PATH=./backend/covers
AUTO_FIX_BANNERS=true
DOWNLOAD_POLL_FALLBACK_SECONDS=60                    # fallback polling if subscription drops
```

---

## Verification Plan
1. Stand up Suwayomi locally, install 2+ sources with different priorities
2. Submit a request → verify highest-priority available source is selected, DB rows created, Suwayomi receives download command
3. After download: verify quality scan fires (via subscription event), severity appears in UI
4. Upload a sample page with a known watermark, crop template in UI → re-scan → verify detection
5. Verify chapter is relocated to `LIBRARY_PATH` with correct naming format; check `library_path` in DB
6. Simulate upgrade: configure a higher-priority source that also has the manga → trigger chapter download → verify upgrade job runs, library file atomically replaced, old staging files deleted
7. Let Otaki's poll job fire for an ongoing series → verify new chapter is detected, best available source selected, downloaded, quality checked, and relocated without manual intervention
8. Test cross-filesystem relocation (different mount points) → verify copy+delete path runs correctly
