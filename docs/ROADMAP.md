# Roadmap

---

## 1.0 — MVP

Goal: download a comic from the best available source, keep it updated, and upgrade to better sources on a schedule.

### Setup & Config
- [ ] First-run setup wizard (Suwayomi connection, source priority ordering, paths)
- [ ] Settings page (edit Suwayomi config, paths, naming format)
- [ ] Docker Compose with backend, frontend, and Suwayomi
- [ ] Fixed global polling interval (`DEFAULT_POLL_DAYS` in config — no per-comic overrides yet)

### Auth
- [ ] Local login (username + password, single admin user for MVP)
- [ ] Basic API endpoint protection (authenticated or not — no roles yet)

### Search & Requests
- [ ] Multi-source search with source labels
- [ ] Request a comic (single title/URL, per-chapter source selection)
- [ ] File relocation to library path (hardlink / copy+delete, atomic upgrade swap)
- [ ] Configurable naming format

### Download & Orchestration
- [ ] Per-chapter source selection (`build_chapter_source_map(comic, db)` — accepts comic object from day one so 1.1 alias support requires no signature change)
- [ ] Otaki-driven new chapter polling (fixed interval)
- [ ] Upgrade checks on fixed schedule — swap whenever a higher-priority source has the chapter, no quality condition yet
- [ ] Download listener (GraphQL subscription + polling fallback)
- [ ] Retry logic for failed downloads

### UI
- [ ] Login page
- [ ] Search page
- [ ] Library page (download progress, source, next poll time)
- [ ] Comic detail page (per-chapter source, download status, library path)
- [ ] Sources page (drag-to-reorder priority, enabled toggle)
- [ ] Settings page

---

## 1.1 — Metadata

Make the library usable in a comic reader without manual cleanup. Also lays the groundwork for better cross-source coverage.

- [ ] `ComicInfo.xml` writing (`<Series>`, `<Number>`, `<Volume>`)
- [ ] Cover management (select from source results or upload file; inject as `cover.png` in every CBZ)
- [ ] Multi-alias support (same series with different names across sources)
- [ ] Library title (separate from display title; used for folder name and `ComicInfo.xml`)
- [ ] Library title rename — move all existing relocated files to the new folder path
- [ ] **Bulk re-process** — re-evaluate source assignments using all aliases, re-inject ComicInfo + cover into existing chapters. Fixes 1.0 chapters that were assigned before aliases existed.
- [ ] Health check endpoint (`GET /api/health`) surfaced in UI

---

## 1.2 — Better Searching & Scale

Stronger cross-source coverage and library management at scale.

- [ ] Comic-local source priority overrides (e.g. source B is better than source A for one specific series)
- [ ] Pagination for Library and Comic detail views
- [ ] Search and filter within tracked library (by source, status)
- [ ] Import existing library (scan pre-existing CBZs into Otaki without re-downloading)
- [ ] Export / backup of Otaki DB, covers, and watermarks

---

## 1.3 — Quality

- [ ] Watermark detection (template matching on first/last page)
- [ ] Banner / header / footer detection (phash)
- [ ] Auto-fix banner cropping (with `.orig` backup)
- [ ] Watermark template manager (upload sample page, draw crop region)
- [ ] Quality severity badges in UI
- [ ] Source quality stats per source (% clean chapters)
- [ ] Upgrade swap condition updated — only swap if new severity ≤ old severity (replaces the always-swap default from 1.0)
- [ ] Image order / cohesion checking (detect scrambled or out-of-sequence pages)
- [ ] Chapter de-duplication (`Ch. 47` vs `Ch. 47 (v2)` on the same source; prefer lowest severity, fall back to source priority)

---

## 1.4 — Auth & Multi-User

- [ ] Reader / Requestor / Admin roles and permission enforcement (the auth middleware stub from 1.0 gets activated)
- [ ] SSO login (OAuth2 / OIDC — Google, GitHub, custom provider)
- [ ] User management page

---

## Future

- [ ] Force-upgrade all — trigger upgrade check for every chapter of a comic in one action
- [ ] Notification support (webhook or Discord on new chapter, upgrade, or quality issue)
- [ ] Additional `ComicInfo.xml` fields from Suwayomi metadata (author, artist, genre, status)

---

## Not Planned

Features explicitly out of scope. Revisit only if there is a clear need.

- Reading progress tracking — Suwayomi handles this; Otaki is a download manager, not a reader
- Multi-Suwayomi-instance support — use separate Otaki deployments
- CBR / PDF support — CBZ only
- Per-page watermark detection (inner pages) — first/last page covers the common case
