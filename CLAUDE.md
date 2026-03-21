# Otaki — LLM Context

This file is the entry point for any LLM assistant working on this project. Read it fully before making any changes.

---

## What Otaki Is

A personal manga/comic request manager that sits on top of a running **Suwayomi-Server** instance. Users search for titles, submit download requests, and Otaki handles source selection, quality checking, automatic source upgrades, and file relocation to a final library. Suwayomi is used only as a **download engine** — Otaki owns all orchestration and decision logic.

---

## Source of Truth

The design lives in these files. Read them before touching any code:

| File | Contains |
|---|---|
| `PLAN.md` | Full design: data model, workflows, config, tech stack |
| `docs/ARCHITECTURE.md` | File-by-file responsibilities, method signatures, worker logic |
| `docs/API.md` | All API endpoints with input/output schemas |
| `docs/FLOWS.md` | Mermaid diagrams for UI and system flows |
| `CONTRIBUTING.md` | Commit conventions, LLM guidelines, doc sync rules |
| `TODO.md` | Known gaps and pending implementation items |

**If your change conflicts with these docs, update the docs in the same commit — do not silently deviate.**

---

## Non-Obvious Design Decisions

These are the things most likely to trip up an LLM. Read carefully.

**Source selection is per-chapter, not per-comic.**
There is no `comic.current_source_id`. Each `ChapterAssignment` row has its own `source_id`. Different chapters of the same comic can come from different sources. This is intentional.

**Otaki drives all polling — Suwayomi does not auto-discover chapters.**
Otaki's APScheduler poll job calls `suwayomi.fetch_chapters()` on all sources and decides what to download. Suwayomi only downloads when Otaki explicitly calls `enqueueChapterDownloads`. Do not add logic that relies on Suwayomi's internal update scheduler.

**Two separate scheduled jobs per comic.**
A **poll job** (checks for new chapters) and an **upgrade job** (checks existing chapters for better sources) run independently with separate configurable intervals. Both default to `inferred_cadence_days` unless overridden by `poll_override_days` / `upgrade_override_days`.

**Cadence is inferred from `chapter_published_at`, not `downloaded_at`.**
`chapter_published_at` is the source's original upload date (Suwayomi's `uploadDate` field). Using `downloaded_at` would cluster all gaps near zero for bulk imports and produce nonsense. The inferrer also filters hiatus gaps (> 3× initial median) before computing the final median.

**`comic.title` and `comic.library_title` are different fields.**
`title` is the display name in the Otaki UI. `library_title` is the canonical name written to `ComicInfo.xml` `<Series>` and used as the folder name in the library. They default to the same value but can differ. Always use `comic.library_title` in `file_relocator` and `comicinfo_writer` — never `comic.title`.

**Search results are not deduplicated — the user picks which results are the same series.**
A comic can have different names on different sources ("One Piece" vs "ワンピース"). The search API returns all results with source labels. The user selects which cards belong to the same series and sets a preferred display title. All selected titles are stored as `ComicAlias` rows and used when searching sources for chapters. `build_chapter_source_map` always receives a `comic` object and queries by all its aliases.

**Per-comic source priority overrides exist.**
`ComicSourceOverride` rows let a specific comic treat a source as a different priority than the global ranking. `source_router.effective_priority()` must be used everywhere priority is evaluated — never read `source.priority` directly in routing logic.

**`chapter_event_handler` does not drive upgrades or polls.**
It only handles: scan → fix → relocate, and the upgrade-swap decision when an upgrade download completes. Scheduling is entirely APScheduler's responsibility.

**Suwayomi is staging; `LIBRARY_PATH` is the final library.**
Files are only moved to the library once a chapter is settled (scanned, fixed if needed). During upgrades, the library file is atomically replaced via `os.replace()` — no window where the file is missing.

**Hardlinks are preferred for relocation.**
Same filesystem → `os.link()`. Different filesystem → `shutil.copy2()` + verify + `os.replace()` + delete staging copy.

---

## Data Model (abbreviated)

```
comics
  id, title, status,
  inferred_cadence_days, poll_override_days, upgrade_override_days,
  next_poll_at, next_upgrade_check_at, last_upgrade_check_at

sources
  id, suwayomi_source_id, name, priority (1=best), enabled

chapter_assignments
  id, comic_id, chapter_number, volume_number, source_id,
  suwayomi_manga_id, suwayomi_chapter_id,
  download_status, is_active,
  chapter_published_at,  ← from Suwayomi uploadDate, used for cadence
  downloaded_at, library_path, relocation_status

quality_scans
  id, chapter_assignment_id, scanned_at,
  watermark_count, watermark_templates_matched,
  has_header, has_footer, severity, auto_fixed

watermark_templates
  id, name, source_id, file_path, match_threshold, enabled

users
  id, username, email, password_hash, sso_provider, sso_sub,
  role (reader|requestor|admin)

comic_aliases
  id, comic_id, title, source_id (nullable)

comic_source_overrides
  id, comic_id, source_id, priority_override
```

---

## Roles and Permissions

| Action | Reader | Requestor | Admin |
|---|:---:|:---:|:---:|
| View library / quality | ✓ | ✓ | ✓ |
| Request comics / upgrades | | ✓ | ✓ |
| Comic-local source overrides | | ✓ | ✓ |
| Global source priority / templates / cadence | | | ✓ |
| User management / settings / SSO | | | ✓ |

---

## Key Services

| File | Responsibility |
|---|---|
| `services/suwayomi.py` | All Suwayomi GraphQL calls. Nothing else imports `gql` directly. |
| `services/source_router.py` | `build_chapter_source_map`, `find_upgrade_candidates`, `effective_priority` |
| `services/cadence_inferrer.py` | Median gap from `chapter_published_at`; hiatus-aware |
| `services/quality_scanner.py` | Scan first + last CBZ pages only; template match + phash banners |
| `services/cover_injector.py` | Download/save cover image; inject as `cover.png` into each chapter CBZ |
| `services/comicinfo_writer.py` | Write/update `ComicInfo.xml` inside CBZ; sets `<Series>` to `library_title` |
| `services/template_extractor.py` | Crop watermark region from user-uploaded page; save PNG; invalidate scanner cache |
| `services/image_processor.py` | Crop banners in-place; always keeps `.cbz.orig` backup |
| `services/file_relocator.py` | `relocate` and `replace_in_library` (atomic swap during upgrades) |
| `workers/download_listener.py` | GraphQL subscription for Suwayomi download events |
| `workers/chapter_event_handler.py` | scan → fix → relocate; upgrade-swap on upgrade download complete |
| `workers/scheduler.py` | APScheduler: two jobs per comic (poll + upgrade) |
| `api/auth.py` | Login, logout, OAuth2 callback, session token, `require_permission` dependency |
| `api/setup.py` | First-run wizard: connect Suwayomi, order sources, set paths |

---

## Issue Workflow

Follow this process for every GitHub issue:

1. **Before starting** — check the issue's blockers. If any blocker is not merged, stop and confirm with the user before proceeding.
2. **When starting** — create a branch from `develop` and open a draft PR linked to the issue. GitHub automation moves the issue to **In Progress**.
3. **When the PR is ready** — mark it as ready for review. GitHub automation moves the issue to **In Review**.
4. **When a PR is merged** — GitHub automation moves the issue to **Done**. Check all issues that were blocked by this one and flag any that are now unblocked to the user.

---


## Rules

- **Do not add features beyond what was asked.** No extra error handling, helpers, or abstractions for hypothetical cases.
- **Do not mock the Suwayomi client in integration tests.** Use a real running instance.
- **Always use `effective_priority(source, comic, db)`** when comparing source priorities — never read `source.priority` raw.
- **Always use `comic.library_title`** (not `comic.title`) in `file_relocator` and `comicinfo_writer`.
- **Always use `chapter_published_at`** for any time-based chapter calculations.
- **Scan first and last CBZ pages only.** Banners appear only there. Do not scan inner pages.
- **Update docs in the same commit as code changes.** See `CONTRIBUTING.md` for which doc to update.
- **Commit format:** `type(scope): description` — see `CONTRIBUTING.md`.
- **Quality threshold for upgrade swap:** new severity must be ≤ old severity. Equal is acceptable (same quality from better source is a win for future upgrades).
