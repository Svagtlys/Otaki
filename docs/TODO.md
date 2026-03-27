# TODO

Items are grouped by area. Add notes inline where context is useful.

---

## Core Implementation

- [ ] Scaffold FastAPI app (`main.py`, `config.py`, `database.py`)
- [ ] Define SQLAlchemy models (`Comic`, `ComicAlias`, `Source`, `ChapterAssignment`, `QualityScan`, `WatermarkTemplate`, `User`, `ComicSourceOverride`)
- [ ] Set up Alembic for migrations
- [ ] Implement `suwayomi.py` GraphQL client (search, add to library, fetch chapters, enqueue, subscribe, delete)
- [ ] Implement `source_selector.py` (`build_chapter_source_map` for per-chapter source assignment, `find_upgrade_candidates` per scheduled check)
- [ ] Implement `download_listener.py` (subscription + exponential backoff + polling fallback)
- [ ] Implement `chapter_event_handler.py` (scan → fix → relocate; handle upgrade swap on upgrade download complete)
- [ ] Implement `cadence_inferrer.py` (compute median chapter release gap from history; called after each poll job)
- [ ] Implement `scheduler.py` (APScheduler setup; register per-comic poll + upgrade jobs on startup and on new comic request; advance `next_poll_at`/`next_upgrade_check_at` after each run)
- [ ] Implement `quality_scanner.py` (template matching + banner phash detection)
- [ ] Implement `template_extractor.py` (crop + save PNG + invalidate cache)
- [ ] Implement `image_processor.py` (crop first/last pages, `.orig` backup, repack CBZ)
- [ ] Implement `comicinfo_writer.py` (write/update `ComicInfo.xml` inside CBZ; set `<Series>` to `library_title`, `<Number>`, `<Volume>`; preserve all other existing fields)
- [ ] Implement `cover_handler.py` (`save_from_url`, `save_from_upload`, `inject` — add/replace `cover.png` in CBZ)
- [ ] Implement `file_relocator.py` (hardlink vs copy+delete, atomic upgrade swap)
- [ ] Implement `auth.py` (local login, OAuth2/OIDC callback, session tokens, `require_permission` dependency)
- [ ] Implement `setup.py` (first-run wizard: connect Suwayomi, order sources, set paths)
- [ ] Wire up all API routers (`auth`, `setup`, `search`, `requests`, `sources`, `quality`)

---

## Frontend

- [ ] Login page (local username/password form + SSO provider buttons)
- [ ] Search page (search bar, result cards with cover + source label, multi-select, primary title / library title picker, cover picker from results or upload, request button)
- [ ] Library page (tracked comics table, severity badges, download progress, next poll/upgrade times)
- [ ] Comic detail page (chapter table, quality badges, tooltips, rescan/autofix/relocate buttons, cadence override, local source priority)
- [ ] Sources page (drag-to-reorder priority list, enabled toggle, quality stats per source)
- [ ] Watermark template manager (image upload, canvas crop selector, template list)
- [ ] Settings page (Suwayomi connection, paths, naming format, auto-fix toggle, SSO config — admin only)
- [ ] User management page (add/edit/remove users, assign roles — admin only)

---

## Quality Detection

- [ ] **Image order / cohesion checking** — detect pages that appear out of sequence within a chapter CBZ
  - Known example: *Infinite Mage* ep 85
  - Possible approach: compare consecutive page dimensions for sudden aspect ratio breaks; use pHash similarity between adjacent pages to flag large perceptual jumps that suggest a misplaced or scrambled page
  - New `QualityScan` fields needed: `has_ordering_issue` (bool), `disordered_page_indices` (JSON list)
  - New severity contribution: ordering issues should push severity to at least `moderate`
  - Needs UI treatment: tooltip on severity badge should surface which pages are suspect

- [ ] **Chapter de-duplication** — handle sources that publish multiple versions of the same chapter number (e.g. `Ch. 47` and `Ch. 47 (v2)`)
  - Suwayomi may return multiple `ChapterAssignment` candidates for the same `chapter_number`
  - Decision logic needed: prefer the version with the lowest severity after scanning; if equal, prefer the one from the higher-priority source
  - Needs a `version_tag` field (nullable string) on `ChapterAssignment` to store Suwayomi's version label
  - `is_active` flag already handles "one canonical copy per chapter" — de-dup logic would set the winner to `is_active=true` and mark losers `is_active=false`
  - UI: collapsed by default per chapter number, expandable to show all versions with their individual quality scores

---

## Reliability & Edge Cases

- [ ] Retry logic for failed downloads (detect `download_status=failed`, re-enqueue)
- [ ] Handle Suwayomi returning duplicate chapter numbers with different `suwayomi_chapter_id` values
- [ ] Graceful degradation when no source has the requested title
- [ ] Handle `library_title` rename after relocation — move all existing library files to new folder path atomically
- [ ] Verify atomic rename behaviour on the target OS/filesystem for relocation
- [ ] Test cross-filesystem relocation (copy+delete path)

---

## Ops / Setup

- [ ] `docker-compose.yml` with backend, frontend, and Suwayomi services
- [ ] `.env.example` with all required variables documented
- [ ] Health check endpoint (`GET /api/health`) that pings Suwayomi and returns DB status
- [ ] README quickstart (Docker Compose up, first source config, first request)
