# Regex-Based Chapter File Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace prefix-based fallback matching in `find_staging_path()` with configurable regex patterns from `.env`, allowing users to match chapter files using patterns like `Mangakakalot_Ch. 61.5`, `Episode 102`, or `(ch. 169)`.

**Architecture:** Store raw regex pattern strings in `CHAPTER_FILE_NAME_REGEX` config field. At runtime in `file_relocator`, replace `{chapter_number}` placeholder with numeric variants and match against file/folder stems using `re.search()`. New matching order: exact CBZ > exact folder > regex CBZ > regex folder > single CBZ fallback > single folder fallback.

**Tech Stack:** Python, pydantic-settings, `re` module, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/config.py` | Modify | Fix validator bug in `validate_regex_patterns` |
| `backend/app/services/file_relocator.py` | Modify | Add `_get_chapter_number_variants`, `_match_by_regex`; restructure `find_staging_path` |
| `backend/tests/test_config_regex.py` | Create | Config parsing and validation tests |
| `backend/tests/test_file_relocator.py` | Modify | Add regex matching and chapter variant tests |
| `.env.example` | Modify | Document `CHAPTER_FILE_NAME_REGEX` |

---

### Task 1: Fix config validator bug

**Files:**
- Modify: `backend/app/config.py:43-52`
- Test: `backend/tests/test_config_regex.py`

The current validator at line 48 discards the `.replace()` result, causing `re.compile(pattern)` to compile the raw string containing `{chapter_number}` which has unbalanced braces and will fail.

- [ ] **Step 1: Create test file with validator tests**

Create `backend/tests/test_config_regex.py`:

```python
"""Tests for CHAPTER_FILE_NAME_REGEX parsing and validation in config."""
import pytest
from pydantic import ValidationError

from app.config import Settings


class TestChapterFileNameRegexValidation:
    def test_accepts_valid_pattern_with_chapter_placeholder(self, tmp_path, monkeypatch):
        """Pattern containing {chapter_number} validates after replacement."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            'CHAPTER_FILE_NAME_REGEX="[\'Chapter {chapter_number}\']"\n'
        )
        monkeypatch.setenv("ENV_FILE", str(env_file))
        # Must not raise
        s = Settings()
        assert s.CHAPTER_FILE_NAME_REGEX == ["Chapter {chapter_number}"]

    def test_rejects_invalid_regex_pattern(self, tmp_path, monkeypatch):
        """Validator raises ValidationError on malformed regex."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            'CHAPTER_FILE_NAME_REGEX="[\'[invalid\']"\n'
        )
        monkeypatch.setenv("ENV_FILE", str(env_file))
        with pytest.raises(ValidationError):
            Settings()

    def test_none_when_not_set(self, tmp_path, monkeypatch):
        """Field is None when env var is absent."""
        env_file = tmp_path / ".env"
        env_file.write_text("")
        monkeypatch.setenv("ENV_FILE", str(env_file))
        s = Settings()
        assert s.CHAPTER_FILE_NAME_REGEX is None

    def test_parses_multiple_patterns(self, tmp_path, monkeypatch):
        """Multiple patterns parse correctly from JSON array."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            'CHAPTER_FILE_NAME_REGEX="[\'Chapter {chapter_number}\', \'(ch. {chapter_number})\']"\n'
        )
        monkeypatch.setenv("ENV_FILE", str(env_file))
        s = Settings()
        assert len(s.CHAPTER_FILE_NAME_REGEX) == 2
        assert "Chapter {chapter_number}" in s.CHAPTER_FILE_NAME_REGEX
        assert "(ch. {chapter_number})" in s.CHAPTER_FILE_NAME_REGEX
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_config_regex.py -v`
Expected: FAIL - validator bug causes `test_accepts_valid_pattern_with_chapter_placeholder` to fail because `{chapter_number}` has unbalanced braces.

- [ ] **Step 3: Fix validator in config.py**

In `backend/app/config.py`, replace lines 43-52:

```python
    @field_validator("CHAPTER_FILE_NAME_REGEX", mode="after")
    @classmethod
    def validate_regex_patterns(cls, value: list[str]) -> list[str]:
        for pattern in value:
            try:
                replaced = pattern.replace("{chapter_number}", "1")
                re.compile(replaced)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}")
        return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_config_regex.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config_regex.py
git commit -m "fix: validate CHAPTER_FILE_NAME_REGEX patterns with placeholder replacement"
```

---

### Task 2: Implement `_get_chapter_number_variants`

**Files:**
- Modify: `backend/app/services/file_relocator.py` (add new function before `find_staging_path`)
- Test: `backend/tests/test_file_relocator.py`

- [ ] **Step 1: Write failing test for chapter number variants**

Add to `backend/tests/test_file_relocator.py`:

```python
# ---------------------------------------------------------------------------
# _get_chapter_number_variants tests
# ---------------------------------------------------------------------------


class TestChapterNumberVariants:
    def test_whole_number_produces_float_and_int_variants(self):
        """5.0 -> ['5.0', '5']"""
        result = file_relocator._get_chapter_number_variants(5.0)
        assert result == ["5.0", "5"]

    def test_fractional_number_produces_single_variant(self):
        """61.5 -> ['61.5']"""
        result = file_relocator._get_chapter_number_variants(61.5)
        assert result == ["61.5"]

    def test_nonzero_decimal_produces_single_variant(self):
        """3.02 -> ['3.02']"""
        result = file_relocator._get_chapter_number_variants(3.02)
        assert result == ["3.02"]

    def test_zero_chapter_produces_variants(self):
        """0.0 -> ['0.0', '0']"""
        result = file_relocator._get_chapter_number_variants(0.0)
        assert result == ["0.0", "0"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_file_relocator.py::TestChapterNumberVariants -v`
Expected: FAIL with `AttributeError: module 'app.services.file_relocator' has no attribute '_get_chapter_number_variants'`

- [ ] **Step 3: Implement `_get_chapter_number_variants`**

Add to `backend/app/services/file_relocator.py` before `find_staging_path` (around line 70):

```python
def _get_chapter_number_variants(chapter_number: float) -> list[str]:
    """Generate string representations of a chapter number for regex substitution.

    Always includes the full float representation. Includes integer form
    only when all decimal digits are zero.

    Examples:
        5.0  -> ['5.0', '5']
        61.5 -> ['61.5']
        3.02 -> ['3.02']
    """
    # Format with one decimal place minimum, preserving trailing decimals
    # Use repr-like formatting to get the canonical float string
    float_str = f"{chapter_number:g}" if chapter_number == int(chapter_number) else str(chapter_number)
    # Ensure we have a consistent float representation
    if "." not in float_str:
        float_str = f"{chapter_number}.0"
    variants = [float_str]
    # Add integer variant only if decimal part is all zeros
    if chapter_number == int(chapter_number):
        variants.append(str(int(chapter_number)))
    return variants
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_file_relocator.py::TestChapterNumberVariants -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/file_relocator.py backend/tests/test_file_relocator.py
git commit -m "feat: add _get_chapter_number_variants helper for regex matching"
```

---

### Task 3: Implement `_match_by_regex`

**Files:**
- Modify: `backend/app/services/file_relocator.py` (add new function)
- Test: `backend/tests/test_file_relocator.py`

- [ ] **Step 1: Write failing test for regex matching**

Add to `backend/tests/test_file_relocator.py`:

```python
# ---------------------------------------------------------------------------
# _match_by_regex tests
# ---------------------------------------------------------------------------


class TestMatchByRegex:
    def test_matches_cbz_by_pattern(self, tmp_path, monkeypatch):
        """Pattern 'MangaSee_Ch. {chapter_number}' matches 'MangaSee_Ch. 5.cbz'."""
        staging = tmp_path / "staging"
        staging.mkdir()
        cbz = staging / "MangaSee_Ch. 5.cbz"
        _make_cbz(cbz)

        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", ["MangaSee_Ch\\. {chapter_number}"])
        result = file_relocator._match_by_regex(staging, 5.0, [".cbz"])
        assert result == [cbz]

    def test_matches_folder_by_pattern(self, tmp_path, monkeypatch):
        """Pattern matches folder name."""
        staging = tmp_path / "staging"
        staging.mkdir()
        folder = staging / "Chapter 10"
        folder.mkdir()

        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", ["Chapter {chapter_number}"])
        result = file_relocator._match_by_regex(staging, 10.0, [])
        assert result == [folder]

    def test_no_match_returns_empty(self, tmp_path, monkeypatch):
        """Non-matching pattern returns empty list."""
        staging = tmp_path / "staging"
        staging.mkdir()
        cbz = staging / "SomeOther_File.cbz"
        _make_cbz(cbz)

        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", ["Chapter {chapter_number}"])
        result = file_relocator._match_by_regex(staging, 5.0, [".cbz"])
        assert result == []

    def test_returns_none_when_config_empty(self, tmp_path, monkeypatch):
        """No patterns configured returns empty list."""
        staging = tmp_path / "staging"
        staging.mkdir()

        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", None)
        result = file_relocator._match_by_regex(staging, 5.0, [".cbz"])
        assert result == []

    def test_deduplicates_matches(self, tmp_path, monkeypatch):
        """Multiple patterns matching same file returns unique results."""
        staging = tmp_path / "staging"
        staging.mkdir()
        cbz = staging / "Chapter 5.cbz"
        _make_cbz(cbz)

        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", [
            "Chapter {chapter_number}",
            "Chapter 5",  # would also match after replacement
        ])
        result = file_relocator._match_by_regex(staging, 5.0, [".cbz"])
        assert result == [cbz]
        assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_file_relocator.py::TestMatchByRegex -v`
Expected: FAIL with `AttributeError: module 'app.services.file_relocator' has no attribute '_match_by_regex'`

- [ ] **Step 3: Implement `_match_by_regex`**

Add to `backend/app/services/file_relocator.py` after `_get_chapter_number_variants`:

```python
def _match_by_regex(
    directory: Path,
    chapter_number: float,
    extensions: list[str],
) -> list[Path]:
    """Match files or folders in *directory* using configured regex patterns.

    Replaces {chapter_number} in each pattern with numeric variants and
    uses re.search() against file/folder stems.

    Returns deduplicated matching paths in first-match order.
    """
    patterns = settings.CHAPTER_FILE_NAME_REGEX
    if not patterns:
        return []

    variants = _get_chapter_number_variants(chapter_number)
    seen = set()
    matches = []

    # Gather candidates based on extension filter
    if extensions:
        ext_patterns = " ".join(f"*{ext}" for ext in extensions)
        candidates = list(directory.glob(ext_patterns)) if directory.is_dir() else []
    else:
        candidates = [p for p in directory.iterdir() if p.is_dir()] if directory.is_dir() else []

    for pattern_str in patterns:
        for variant in variants:
            try:
                compiled = re.compile(pattern_str.replace("{chapter_number}", variant))
            except re.error:
                continue
            for candidate in candidates:
                if candidate in seen:
                    continue
                if compiled.search(candidate.stem):
                    matches.append(candidate)
                    seen.add(candidate)

    return matches
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_file_relocator.py::TestMatchByRegex -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/file_relocator.py backend/tests/test_file_relocator.py
git commit -m "feat: add _match_by_regex helper for pattern-based file matching"
```

---

### Task 4: Restructure `find_staging_path` with new matching order

**Files:**
- Modify: `backend/app/services/file_relocator.py:72-150` (function signature + body)
- Modify: `backend/app/services/file_relocator.py:310` (`relocate` caller)
- Modify: `backend/app/services/file_relocator.py:376` (`replace_in_library` caller)
- Modify: `backend/app/api/requests.py:655-657` (caller)
- Modify: `backend/app/api/requests.py:729-731` (caller)
- Modify: `backend/tests/test_file_relocator.py` (update all existing + add new tests)
- Test: `backend/tests/test_file_relocator.py`

New order:
1. Exact CBZ match
2. Exact folder match
3. Regex CBZ match
4. Regex folder match
5. Single CBZ fallback
6. Single folder fallback

Remove: CBZ Fallback 2 (prefix match lines 122-129) and folder prefix match (lines 140-143)

Add `chapter_number: float` parameter to `find_staging_path`. Callers already have `assignment.chapter_number` available.

- [ ] **Step 1: Write failing integration tests**

Add to `backend/tests/test_file_relocator.py`:

```python
# ---------------------------------------------------------------------------
# find_staging_path regex integration tests
# ---------------------------------------------------------------------------


class TestFindStagingPathRegex:
    def test_regex_cbz_takes_priority_over_single_fallback(self, tmp_path, monkeypatch):
        """When multiple CBZs exist, regex match wins over single-CBZ fallback."""
        downloads = tmp_path / "downloads"
        source_dir = downloads / "TestSource"
        manga_dir = source_dir / "My Manga"
        manga_dir.mkdir(parents=True)

        # Two CBZs present - single fallback would be ambiguous
        (manga_dir / "MangaSee_Ch. 5.cbz").write_bytes(b"zip")
        _make_cbz(manga_dir / "Other_Chapter.cbz")

        monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", ["MangaSee_Ch\\. {chapter_number}"])

        result = file_relocator.find_staging_path("Unknown Name", "My Manga", "TestSource", 5.0)
        assert result == manga_dir / "MangaSee_Ch. 5.cbz"

    def test_regex_folder_takes_priority_over_single_fallback(self, tmp_path, monkeypatch):
        """When multiple folders exist, regex match wins over single-folder fallback."""
        downloads = tmp_path / "downloads"
        source_dir = downloads / "TestSource"
        manga_dir = source_dir / "My Manga"
        manga_dir.mkdir(parents=True)

        # Two folders present - single fallback would be ambiguous
        (manga_dir / "Chapter 10").mkdir()
        (manga_dir / "Other Folder").mkdir()

        monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", ["Chapter {chapter_number}"])

        result = file_relocator.find_staging_path("Unknown Name", "My Manga", "TestSource", 10.0)
        assert result == manga_dir / "Chapter 10"

    def test_exact_match_takes_priority_over_regex(self, tmp_path, monkeypatch):
        """Exact CBZ match takes priority over regex match."""
        downloads = tmp_path / "downloads"
        source_dir = downloads / "TestSource"
        manga_dir = source_dir / "My Manga"
        manga_dir.mkdir(parents=True)

        exact_cbz = manga_dir / "Episode 5.cbz"
        _make_cbz(exact_cbz)
        # A regex-matching file also exists
        _make_cbz(manga_dir / "MangaSee_Ch. 5.cbz")

        monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", ["MangaSee_Ch\\. {chapter_number}"])

        result = file_relocator.find_staging_path("Episode 5", "My Manga", "TestSource", 5.0)
        assert result == exact_cbz

    def test_regex_cbz_uses_chapter_number_variant(self, tmp_path, monkeypatch):
        """Pattern with integer variant matches when chapter is 5.0."""
        downloads = tmp_path / "downloads"
        source_dir = downloads / "TestSource"
        manga_dir = source_dir / "My Manga"
        manga_dir.mkdir(parents=True)

        # File uses integer form "Chapter 5" not "Chapter 5.0"
        cbz = manga_dir / "Chapter 5.cbz"
        _make_cbz(cbz)

        monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", ["Chapter {chapter_number}"])

        result = file_relocator.find_staging_path("Unknown", "My Manga", "TestSource", 5.0)
        assert result == cbz

    def test_prefix_fallback_removed_for_cbz(self, tmp_path, monkeypatch):
        """Old prefix-based CBZ fallback no longer exists."""
        downloads = tmp_path / "downloads"
        source_dir = downloads / "TestSource"
        manga_dir = source_dir / "My Manga"
        manga_dir.mkdir(parents=True)

        # Old fallback 2 would match "Official_Episode 148.cbz" for chapter "Episode 148"
        cbz = manga_dir / "Official_Episode 148.cbz"
        _make_cbz(cbz)

        monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", None)

        # Without regex config, and no exact match, should return None
        result = file_relocator.find_staging_path("Episode 148", "My Manga", "TestSource", 148.0)
        assert result is None

    def test_prefix_fallback_removed_for_folder(self, tmp_path, monkeypatch):
        """Old prefix-based folder fallback no longer exists."""
        downloads = tmp_path / "downloads"
        source_dir = downloads / "TestSource"
        manga_dir = source_dir / "My Manga"
        manga_dir.mkdir(parents=True)

        # Old prefix folder fallback would match "Official_Episode 148" folder
        (manga_dir / "Official_Episode 148").mkdir()

        monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
        monkeypatch.setattr(settings, "CHAPTER_FILE_NAME_REGEX", None)

        result = file_relocator.find_staging_path("Episode 148", "My Manga", "TestSource", 148.0)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_file_relocator.py::TestFindStagingPathRegex -v`
Expected: FAIL - tests expect 4-arg signature and regex matching, but current impl uses 3-arg signature and prefix matching

- [ ] **Step 3: Update `find_staging_path` signature**

Change function signature in `backend/app/services/file_relocator.py:72`:

```python
def find_staging_path(
    chapter_name: str, manga_title: str, source_display_name: str, chapter_number: float
) -> Path | None:
```

- [ ] **Step 4: Update all production callers**

Update `backend/app/services/file_relocator.py:310` (`relocate` function):

```python
staging = find_staging_path(chapter_name, manga_title, source_display_name, assignment.chapter_number)
```

Update `backend/app/services/file_relocator.py:376` (`replace_in_library` function):

```python
staging = find_staging_path(chapter_name, manga_title, source_display_name, new.chapter_number)
```

Update `backend/app/api/requests.py:655-657`:

```python
staging = file_relocator.find_staging_path(
    chapter_name, manga_title, source_display_name, assignment.chapter_number
)
```

Update `backend/app/api/requests.py:729-731`:

```python
staging = file_relocator.find_staging_path(
    chapter_name, manga_title, source_display_name, assignment.chapter_number
)
```

- [ ] **Step 5: Restructure matching logic in `find_staging_path`**

Replace the matching section (lines 114-150 in `backend/app/services/file_relocator.py`):

```python
    # --- 1. Exact CBZ match ---
    exact = base / f"{chapter_name}.cbz"
    if exact.exists():
        return exact

    # --- 2. Exact folder match ---
    exact_folder = base / chapter_name
    if exact_folder.is_dir():
        return exact_folder

    # --- 3. Regex CBZ match ---
    cbz_matches = _match_by_regex(base, chapter_number, [".cbz"])
    if len(cbz_matches) == 1:
        return cbz_matches[0]

    # --- 4. Regex folder match ---
    folder_matches = _match_by_regex(base, chapter_number, [])
    if len(folder_matches) == 1:
        return folder_matches[0]

    # --- 5. Single CBZ fallback ---
    matches = list(base.glob("*.cbz"))
    if len(matches) == 1:
        return matches[0]

    # --- 6. Single folder fallback ---
    subdirs = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
    if len(subdirs) == 1:
        return subdirs[0]

    logger.warning(
        "file_relocator: ambiguous or missing staging file for chapter %r in %s",
        chapter_name,
        base,
    )
    return None
```

- [ ] **Step 6: Update existing test calls to use 4-arg signature**

All existing `find_staging_path` test calls in `backend/tests/test_file_relocator.py` must be updated from 3-arg to 4-arg. Add `chapter_number` argument (use `1.0` or appropriate value for each test). Search for `find_staging_path(` in the test file and add the 4th argument to each call.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_file_relocator.py::TestFindStagingPathRegex -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Run full test suite to check for regressions**

Run: `cd backend && python -m pytest tests/test_file_relocator.py -v`
Expected: All existing tests still pass

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/file_relocator.py backend/tests/test_file_relocator.py
git commit -m "feat: restructure find_staging_path with regex matching, remove prefix fallbacks"
```

---

### Task 5: Update `.env.example` documentation

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add CHAPTER_FILE_NAME_REGEX documentation to `.env.example`**

Append to `.env.example` after `MAX_DOWNLOAD_RETRIES`:

```ini
# Chapter file name regex patterns for fuzzy matching.
# Each pattern uses {chapter_number} as a placeholder replaced at runtime.
# Patterns are tried in order; first unique match wins.
# Pattern 1 - Scan-group prefix + chapter/episode keyword:
#   Matches: "Mangakakalot_Ch. 61.5", "Unknown_Episode 163", "WebToon_Chapter 63.02"
# Pattern 2 - Clean chapter/episode keyword with optional trailing text:
#   Matches: "Chapter 131_ Afterword", "Episode 102 (ch. 102)"
# Pattern 3 - Free-form text with parenthetical chapter marker:
#   Matches: "Prologue (ch. 0)", "(S4) Ep. 169 - Gram (ch. 169)"
# CHAPTER_FILE_NAME_REGEX="[
#     '[A-Za-z]+_(Chapter|Episode|Ch)\\.?\\s*{chapter_number}',
#     '(Chapter|Episode)\\s+{chapter_number}',
#     '\\(ch\\.\\s*{chapter_number}\\)'
# ]"
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add CHAPTER_FILE_NAME_REGEX to .env.example"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Config validator fix (Task 1), variant helper (Task 2), regex matching (Task 3), restructured `find_staging_path` (Task 4), documentation (Task 5)
- [x] **Placeholder scan:** No TBDs, TODOs, or vague instructions
- [x] **Type consistency:** `_get_chapter_number_variants(float) -> list[str]`, `_match_by_regex(Path, float, list[str]) -> list[Path]`, `find_staging_path(..., chapter_number: float)`
- [x] **Test coverage:** Config validation, variant generation, regex matching, integration tests for priority ordering, regression tests for removed fallbacks

## Notes for Implementation

- Callers of `find_staging_path`: `relocate()` (line 310), `replace_in_library()` (line 376) in `file_relocator.py`, and two calls in `requests.py` (lines 655, 729). All have `assignment.chapter_number` available.
- Existing tests calling `find_staging_path` with 3 args must be updated to 4 args. Use appropriate chapter numbers matching the test scenario.
- Tests relying on old prefix-based fallback behavior (CBZ Fallback 2, folder prefix match) may need updating or removal since those fallbacks are being removed.
