# Regex-Based Chapter File Matching

**Date:** 2026-06-19
**Status:** Draft

## Overview

Replace prefix-based fallback matching in `find_staging_path()` with configurable regex patterns from `.env`. Users define patterns containing `{chapter_number}` placeholder; at runtime the placeholder is replaced with chapter number variants and matched against file/folder stems.

## Problem

The current fallback matching in [`find_staging_path()`](backend/app/services/file_relocator.py:72) uses `startswith`-style prefix matching (lines 122-129 for CBZ, 140-143 for folders). This doesn't handle the three common naming schemas used by scan groups:

| Schema | Example Files | Pattern |
|--------|---------------|---------|
| **1. Scan-group prefix + chapter keyword** | `Mangakakalot_Ch. 61.5.cbz`, `Unknown_Episode 163.cbz`, `WebToon_Chapter 63.02.cbz` | `Prefix_Ch\\. {chapter_number}` |
| **2. Clean chapter/episode keyword** | `Chapter 131_ Afterword.cbz`, `Episode 102 (ch. 102).cbz` | `(Chapter\|Episode)\s+{chapter_number}` |
| **3. Parenthetical chapter marker** | `Prologue (ch. 0).cbz`, `(S4) Ep. 169 - Gram (ch. 169).cbz` | `\\(ch\\. {chapter_number}\\)` |

## Solution

Store regex patterns in `.env` via `CHAPTER_FILE_NAME_REGEX`. At runtime, replace `{chapter_number}` with chapter number variants and match against file/folder stems using `re.search()`.

### Example `.env` Configuration

```ini
# Pattern 1 — Scan-group prefix + chapter/episode keyword
# Matches: "Mangakakalot_Ch. 61.5", "Unknown_Episode 163", "WebToon_Chapter 63.02"
# Pattern 2 — Clean chapter/episode keyword with optional trailing text
# Matches: "Chapter 131_ Afterword", "Episode 102 (ch. 102)"
# Pattern 3 — Free-form text with parenthetical chapter marker
# Matches: "Prologue (ch. 0)", "(S4) Ep. 169 - Gram (ch. 169)"
CHAPTER_FILE_NAME_REGEX="[
    '[A-Za-z]+_(Chapter|Episode|Ch)\\.?\\s*{chapter_number}',
    '(Chapter|Episode)\\s+{chapter_number}',
    '\\(ch\\.\\s*{chapter_number}\\)'
]"
```

## Solution

Store regex patterns in `.env` via `CHAPTER_FILE_NAME_REGEX`. At runtime, replace `{chapter_number}` with numeric variants and match against file/folder stems using `re.search()`.

## Configuration

### `.env` Format

```ini
CHAPTER_FILE_NAME_REGEX="[
    'Mangakakalot_Ch\\. {chapter_number}',
    'Episode {chapter_number}',
    '\\(ch\\. {chapter_number}\\)'
]"
```

JSON array of strings, parsed by pydantic-settings from `.env`.

### Config Changes ([`config.py`](backend/app/config.py:1))

1. **Fix validator bug** (line 48): The current `.replace()` result is discarded. Must assign before `re.compile()`:
   ```python
   replaced = pattern.replace("{chapter_number}", "1")
   re.compile(replaced)
   ```
2. Field remains `list[str] | None` — raw pattern strings stored, no pre-compilation.

## File Relocator Changes

### New Helper: `_get_chapter_number_variants`

Generates string representations of a chapter number for regex substitution:

| Input | Output |
|-------|--------|
| `5.0` | `["5.0", "5"]` |
| `61.5` | `["61.5"]` |
| `3.02` | `["3.02"]` |
| `1.0` | `["1.0", "1"]` |

**Rule:** Always include the full float representation. Include integer form only when all decimal digits are zero.

### New Helper: `_match_by_regex`

```python
def _match_by_regex(
    directory: Path,
    chapter_number: float,
    extensions: list[str]  # [".cbz"] or [] for folders
) -> list[Path]:
```

- Iterate each pattern from `settings.CHAPTER_FILE_NAME_REGEX`
- For each variant from `_get_chapter_number_variants(chapter_number)`:
  - Replace `{chapter_number}` in pattern
  - Compile regex
  - `re.search()` against each file/folder stem in `directory`
- Return deduplicated matching paths (preserving first-match order)

### Revised `find_staging_path` Order

```
1. Exact CBZ match            (base / "chapter_name.cbz")
2. Exact folder match         (base / "chapter_name")
3. Regex CBZ match            (new - replaces old Fallback 2)
4. Regex folder match         (new - replaces old prefix match)
5. Single CBZ fallback        (only one .cbz in directory)
6. Single folder fallback     (only one subdirectory)
```

**Removed:**
- CBZ Fallback 2 (prefix match, lines 122-129)
- Folder prefix match (lines 140-143)

## Testing Plan (Red-Green TDD)

### Config Tests (`backend/tests/test_config_regex.py`)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_parses_valid_regex_list_from_env` | Valid JSON array parses correctly from `.env` |
| 2 | `test_rejects_invalid_regex_pattern` | Validator raises `ValidationError` on malformed regex |
| 3 | `test_accepts_pattern_with_chapter_placeholder` | Pattern containing `{chapter_number}` validates after replacement |
| 4 | `test_none_when_not_set` | Field is `None` when env var absent |

### File Relocator Tests (`backend/tests/test_file_relocator.py`)

| # | Test | Description |
|---|------|-------------|
| 5 | `test_chapter_number_variants_whole` | `5.0` → `["5.0", "5"]` |
| 6 | `test_chapter_number_variants_fractional` | `61.5` → `["61.5"]` |
| 7 | `test_match_by_regex_finds_cbz` | Pattern matches CBZ file stem |
| 8 | `test_match_by_regex_returns_multiple` | Multiple patterns matching same file deduplicates |
| 9 | `test_find_staging_path_regex_cbz_priority` | Regex CBZ match takes priority over single-CBZ fallback |
| 10 | `test_find_staging_path_regex_folder_priority` | Regex folder match takes priority over single-folder fallback |
| 11 | `test_find_staging_path_exact_over_regex` | Exact match takes priority over regex |
| 12 | `test_find_staging_path_removes_prefix_fallback_cbz` | Old prefix-based CBZ fallback no longer exists |
| 13 | `test_find_staging_path_removes_prefix_fallback_folder` | Old prefix-based folder fallback no longer exists |

## Files Changed

| File | Changes |
|------|---------|
| `backend/app/config.py` | Fix validator bug (line 48) |
| `backend/app/services/file_relocator.py` | Add helpers, restructure `find_staging_path()`, remove prefix fallbacks |
| `backend/tests/test_config_regex.py` | New file — config validation tests |
| `backend/tests/test_file_relocator.py` | Add regex matching tests |
| `.env.example` | Add `CHAPTER_FILE_NAME_REGEX` documentation |
