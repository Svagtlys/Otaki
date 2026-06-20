# AGENTS.md - Architect Mode Rules

This file provides architectural guidance specific to this repository.

## Critical Architecture Rules (Non-Obvious)

- **Otaki drives ALL polling** - Suwayomi does not auto-discover chapters. APScheduler jobs call `suwayomi.fetch_chapters()` and decide what to download.
- **`chapter_event_handler` does NOT drive upgrades or polls** - it only handles: scan → fix → relocate, and upgrade-swap decisions when downloads complete.
- **Suwayomi is staging; `LIBRARY_PATH` is final library** - files move to library only when chapter is settled (scanned, fixed if needed).
- **Atomic file replacement during upgrades** - uses `os.replace()` so the library file is never missing during source upgrades.
- **Hardlinks preferred for relocation** - same filesystem uses `os.link()`, cross-filesystem uses copy + verify + replace pattern.
- **Cadence inference filters hiatus gaps** - gaps > 3x median are excluded before computing final median from `chapter_published_at`.
- **Per-comic source priority overrides** - `ComicSourceOverride` rows let specific comics treat sources differently than global ranking.
