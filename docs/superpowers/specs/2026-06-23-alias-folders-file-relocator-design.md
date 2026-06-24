# Design: Alias Folder Search in File Relocator

**Date:** 2026-06-23
**Issue:** [#169](https://github.com/Svagtlys/Otaki/issues/169)
**PR:** [#178](https://github.com/Svagtlys/Otaki/pull/178)
**Branch:** `fix/alias-folders-file-relocator`

## Problem

`file_relocator.find_staging_path()` only searches the primary comic title folder for chapter files in Suwayomi's staging directory. Some comics download to folders named after their aliases (not the primary title). When this happens, relocation fails because the staging file cannot be found.

Additionally, `requests.py` `reprocess_chapters()` references an undefined `manga_title` variable at six call sites, causing the reprocess endpoint to fail.

## Solution

Refactor `find_staging_path()` to accept `Comic` and `ChapterAssignment` domain objects instead of individual primitive parameters. The function derives manga titles (primary title + aliases) from the `Comic` object and chapter number from the `ChapterAssignment`. This makes the API resilient to future model changes — if new title-related fields are added to `Comic`, the function automatically benefits without signature changes.

`relocate()` and `replace_in_library()` similarly derive manga titles from their `Comic` parameter, removing the need for callers to construct title lists manually.

## Architecture

### Modified Function Signatures

```python
# Before
def find_staging_path(
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
    chapter_number: float,
) -> Path | None:

async def relocate(
    assignment: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
) -> None:

# After
def find_staging_path(
    assignment: ChapterAssignment,
    comic: Comic,
    chapter_name: str,
    source_display_name: str,
) -> Path | None:

async def relocate(
    assignment: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    source_display_name: str,
) -> None:
```

### New Helper: `_build_manga_titles(comic: Comic) -> list[str]`

Extracts the ordered list of folder names from a `Comic` object:

```python
def _build_manga_titles(comic: Comic) -> list[str]:
    titles = [comic.title]
    for alias in comic.aliases:
        titles.append(alias.title)
    return titles
```

### Internal Logic Change

`find_staging_path()` calls `_build_manga_titles(comic)` and loops through each title. The existing per-title search logic is extracted to `_find_staging_path_for_title()` (the original search pipeline, unchanged):

1. Exact source directory match → `_find_manga_subdir()`
2. Fuzzy source directory fallback (if exact fails)
3. Within the manga subdirectory: exact CBZ → exact folder → regex CBZ → regex folder → single CBZ → single folder

### Callers

| Caller | Location | Change |
|--------|----------|--------|
| `_relocate_sync` | `file_relocator.py:367` | Derives titles from `comic` internally |
| `_replace_in_library_sync` | `file_relocator.py:434` | Derives titles from `comic` internally |
| `relocate()` | `file_relocator.py:348` | Removed `manga_title` parameter |
| `replace_in_library()` | `file_relocator.py:413` | Removed `manga_title` parameter |
| `handle()` | `chapter_event_handler.py:24` | Loads Comic with `selectinload(Comic.aliases)`, removes `manga_title` param |
| `reprocess_chapters()` | `requests.py:665` | Loads Comic with `selectinload(Comic.aliases)`, removes `manga_title` variable |

### requests.py manga_title Fix

The undefined `manga_title` variable is eliminated entirely. `reprocess_chapters()` loads the `Comic` with `selectinload(Comic.aliases)` and passes it to `file_relocator` functions, which derive titles internally.

## Data Flow

```
chapter_event_handler.handle() / requests.py reprocess_chapters()
  │
  ├─ Load Comic with selectinload(Comic.aliases)
  │
  ▼
find_staging_path(assignment, comic, chapter_name, source_display_name)
  │
  ├─ _build_manga_titles(comic) → [comic.title, *alias_titles]
  │
  ├─ For each title in titles:
  │    ├─ Try exact source dir → _find_manga_subdir(source_dir, title)
  │    ├─ If None, try fuzzy source fallback
  │    ├─ Within manga subdir: exact CBZ, exact folder, regex CBZ, regex folder, single fallbacks
  │    └─ If chapter file found → return Path immediately
  │
  └─ No match after all titles → return None (relocation fails)
```

## Error Handling

- **Multiple titles match in different directories:** First title wins (primary > aliases).
- **Ambiguous matches within a single directory:** Existing behavior preserved — returns `None` and logs warning.
- **Logging:** Warnings now include the title being searched.

## Testing Strategy

### Unit Tests for `find_staging_path()`
- Chapter found in primary title folder (existing behavior preserved)
- Chapter found in alias folder (new behavior)
- Chapter found in second alias folder (skipping first)
- Chapter not found in any folder (returns `None`)
- Comic with no aliases searches only primary title

### Tests for callers
- `chapter_event_handler` loads Comic with aliases
- `requests.py` reprocess loads Comic with aliases

### Existing test updates
- `_make_comic()` helper gains `aliases` parameter
- All existing tests updated to pass Comic/Assignment objects

## Files Modified

| File | Change |
|------|--------|
| `backend/app/services/file_relocator.py` | New helper, refactored `find_staging_path`, simplified `relocate`/`replace_in_library` signatures |
| `backend/app/workers/chapter_event_handler.py` | Load Comic with aliases, remove `manga_title` param |
| `backend/app/api/requests.py` | Load Comic with aliases, remove undefined `manga_title` |
| `backend/tests/test_file_relocator.py` | Update helpers, update existing tests, add alias tests |

## Out of Scope

- Alias searching for `library_title` (library path resolution uses `comic.library_title` which is the canonical name)
- Alias searching in Suwayomi download queue (Suwayomi uses its own manga title)
- Performance optimization (alias count is expected to be small, < 10)
