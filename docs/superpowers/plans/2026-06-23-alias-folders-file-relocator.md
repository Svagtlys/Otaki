# Alias Folders File Relocator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `find_staging_path()` to search alias-named folders in Suwayomi staging, and fix undefined `manga_title` in `requests.py` reprocess endpoint.

**Architecture:** Refactor `find_staging_path()` to accept `Comic` and `ChapterAssignment` domain objects instead of individual primitive parameters. The function derives manga titles (primary + aliases) from the `Comic` object and chapter number from the `ChapterAssignment`. This makes the API resilient to future model changes. `source_display_name` remains a parameter since it comes from the Suwayomi API. `chapter_name` remains a parameter since it may come from Suwayomi events.

**Tech Stack:** Python 3.13, pytest, FastAPI, SQLAlchemy async

---

## File Structure

| File | Role |
|------|------|
| `backend/app/services/file_relocator.py` | Core change: `find_staging_path()` accepts Comic + ChapterAssignment; `relocate()` / `replace_in_library()` derive manga_titles from Comic |
| `backend/app/workers/chapter_event_handler.py` | Load Comic with aliases eagerly, pass to file_relocator |
| `backend/app/api/requests.py` | Fix undefined `manga_title`, load Comic with aliases, pass to file_relocator |
| `backend/tests/test_file_relocator.py` | Update tests to pass Comic/Assignment objects; add alias-search tests |

---

### Task 1: Add `_build_manga_titles` helper and refactor `find_staging_path()`

**Files:**
- Modify: `backend/app/services/file_relocator.py:144-221`
- Test: `backend/tests/test_file_relocator.py`

- [ ] **Step 1: Write failing tests for alias folder search**

Add these tests to `backend/tests/test_file_relocator.py`:

```python
# ---------------------------------------------------------------------------
# Alias folder search tests
# ---------------------------------------------------------------------------


def test_find_staging_path_found_in_alias_folder(tmp_path, monkeypatch):
    """Chapter file exists in alias folder, not primary title folder."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    comic = _make_comic(
        title="My Comic",
        library_title="My Comic Library",
        aliases=[SimpleNamespace(title="My Comic Alt")],
    )
    assignment = _make_assignment(chapter_number=1.0)
    chapter_name = "Chapter 1"
    source_display = "TestSource"

    # Primary title folder exists but has no chapter file
    (downloads / source_display / "My Comic").mkdir(parents=True)

    # Alias folder has the chapter file
    alias_dir = downloads / source_display / "My Comic Alt"
    alias_dir.mkdir(parents=True)
    cbz = alias_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(
        assignment, comic, chapter_name, source_display
    )

    assert result == cbz


def test_find_staging_path_primary_title_takes_priority(tmp_path, monkeypatch):
    """When both primary and alias folders have the file, primary wins."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    comic = _make_comic(
        title="My Comic",
        library_title="My Comic Library",
        aliases=[SimpleNamespace(title="My Comic Alt")],
    )
    assignment = _make_assignment(chapter_number=1.0)
    chapter_name = "Chapter 1"
    source_display = "TestSource"

    primary_dir = downloads / source_display / "My Comic"
    primary_dir.mkdir(parents=True)
    primary_cbz = primary_dir / f"{chapter_name}.cbz"
    _make_cbz(primary_cbz)

    alias_dir = downloads / source_display / "My Comic Alt"
    alias_dir.mkdir(parents=True)
    alias_cbz = alias_dir / f"{chapter_name}.cbz"
    _make_cbz(alias_cbz)

    result = file_relocator.find_staging_path(
        assignment, comic, chapter_name, source_display
    )

    assert result == primary_cbz


def test_find_staging_path_not_found_in_any_title(tmp_path, monkeypatch):
    """Chapter file missing from all title folders returns None."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    comic = _make_comic(
        title="My Comic",
        library_title="My Comic Library",
        aliases=[SimpleNamespace(title="My Comic Alt")],
    )
    assignment = _make_assignment(chapter_number=1.0)
    chapter_name = "Chapter 1"
    source_display = "TestSource"

    for title in ["My Comic", "My Comic Alt"]:
        d = downloads / source_display / title
        d.mkdir(parents=True)

    result = file_relocator.find_staging_path(
        assignment, comic, chapter_name, source_display
    )

    assert result is None


def test_find_staging_path_no_aliases_searches_only_primary(tmp_path, monkeypatch):
    """Comic with no aliases searches only the primary title folder."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    comic = _make_comic(title="My Comic", library_title="My Comic Library", aliases=[])
    assignment = _make_assignment(chapter_number=1.0)
    chapter_name = "Chapter 1"
    source_display = "TestSource"

    manga_dir = downloads / source_display / "My Comic"
    manga_dir.mkdir(parents=True)
    cbz = manga_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(
        assignment, comic, chapter_name, source_display
    )

    assert result == cbz


def test_find_staging_path_skips_to_second_alias(tmp_path, monkeypatch):
    """File is in the second alias folder, skipping the first."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    comic = _make_comic(
        title="Primary",
        library_title="Primary Library",
        aliases=[
            SimpleNamespace(title="Alias One"),
            SimpleNamespace(title="Alias Two"),
        ],
    )
    assignment = _make_assignment(chapter_number=1.0)
    chapter_name = "Chapter 1"
    source_display = "TestSource"

    (downloads / source_display / "Primary").mkdir(parents=True)
    (downloads / source_display / "Alias One").mkdir(parents=True)
    alias2_dir = downloads / source_display / "Alias Two"
    alias2_dir.mkdir(parents=True)
    cbz = alias2_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(
        assignment, comic, chapter_name, source_display
    )

    assert result == cbz
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/bin/pytest backend/tests/test_file_relocator.py::test_find_staging_path_found_in_alias_folder -v`
Expected: FAIL — `find_staging_path` signature has changed

- [ ] **Step 3: Add `_build_manga_titles` helper and refactor `find_staging_path()`**

Add this helper near the top of `file_relocator.py` (after imports, before `find_staging_path`):

```python
def _build_manga_titles(comic: Comic) -> list[str]:
    """Build ordered list of folder names to search: primary title + aliases."""
    titles = [comic.title]
    for alias in comic.aliases:
        titles.append(alias.title)
    return titles
```

Replace `find_staging_path()` (lines 144-221) with:

```python
def find_staging_path(
    assignment: ChapterAssignment,
    comic: Comic,
    chapter_name: str,
    source_display_name: str,
) -> Path | None:
    """Find a chapter's staging file by searching through title and alias folders.

    Derives manga titles from the Comic (primary title + aliases) and chapter
    number from the ChapterAssignment. Tries each title folder in order and
    returns the first successful match.
    """
    manga_titles = _build_manga_titles(comic)
    chapter_number = assignment.chapter_number

    if not manga_titles:
        return None

    for manga_title in manga_titles:
        if manga_title == "":
            continue
        result = _find_staging_path_for_title(
            chapter_name, manga_title, source_display_name, chapter_number
        )
        if result is not None:
            return result

    return None


def _find_staging_path_for_title(
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
    chapter_number: float,
) -> Path | None:
    """Search for a chapter file under a single manga title directory.

    This is the internal search logic that runs for each title in the alias list.
    """
    source_dir = Path(settings.SUWAYOMI_DOWNLOAD_PATH) / source_display_name
    base = _find_manga_subdir(source_dir, manga_title)

    if base is None:
        download_root = Path(settings.SUWAYOMI_DOWNLOAD_PATH)
        norm_display = _normalize_source_name(source_display_name)
        candidates = [
            d
            for d in download_root.iterdir()
            if d.is_dir()
            and _normalize_source_name(d.name).startswith(norm_display)
            and _find_manga_subdir(d, manga_title) is not None
        ]
        if len(candidates) == 1:
            logger.warning(
                "file_relocator: source dir %r not found; using fuzzy match %r for display name %r (title %r)",
                source_display_name,
                candidates[0].name,
                source_display_name,
                manga_title,
            )
            base = _find_manga_subdir(candidates[0], manga_title)
        elif len(candidates) > 1:
            logger.warning(
                "file_relocator: ambiguous source directory for display name %r — "
                "multiple fuzzy matches: %s (title %r)",
                source_display_name,
                [d.name for d in candidates],
                manga_title,
            )
            return None

    if base is None:
        base = source_dir / manga_title

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
        "file_relocator: ambiguous or missing staging file for chapter %r in %s (title %r)",
        chapter_name,
        base,
        manga_title,
    )
    return None
```

- [ ] **Step 4: Run new alias tests to verify they pass**

Run: `backend/.venv/bin/pytest backend/tests/test_file_relocator.py -k "alias" -v`
Expected: All 5 alias tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/file_relocator.py backend/tests/test_file_relocator.py
git commit -m "feat: search alias folders in find_staging_path (#169)"
```

---

### Task 2: Update `relocate()` and `replace_in_library()` to use Comic/Assignment

**Files:**
- Modify: `backend/app/services/file_relocator.py:348-481`

- [ ] **Step 1: Update `relocate()` and `_relocate_sync()` signatures**

The `relocate()` function already receives `assignment` and `comic`. Update it to derive `manga_titles` from the comic and pass to `find_staging_path`:

```python
async def relocate(
    assignment: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    source_display_name: str,
) -> None:
    await asyncio.to_thread(
        _relocate_sync,
        assignment,
        comic,
        db,
        chapter_name,
        source_display_name,
    )


def _relocate_sync(
    assignment: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    source_display_name: str,
) -> None:
    manga_titles = _build_manga_titles(comic)
    logger.info(
        "relocate: starting for comic=%r chapter=%r source=%r",
        comic.title,
        chapter_name,
        source_display_name,
    )
    staging = find_staging_path(
        assignment, comic, chapter_name, source_display_name
    )
```

Update the warning and final logs:

```python
    if staging is None:
        logger.warning(
            "relocate: no staging file found for comic=%r chapter=%r source=%r — marking failed",
            comic.title,
            chapter_name,
            source_display_name,
        )
        assignment.relocation_status = RelocationStatus.failed
        return

    # ... (keep existing normalization, comicinfo, cover, pack, place logic)

    logger.info(
        "relocate: done for comic=%r chapter=%r -> %s", comic.title, chapter_name, dest
    )
```

**Key change:** Remove `manga_title` parameter from both signatures. Use `comic.title` for logging and `find_staging_path(assignment, comic, chapter_name, source_display_name)` for the staging lookup.

- [ ] **Step 2: Update `replace_in_library()` and `_replace_in_library_sync()`**

Same pattern — remove `manga_title` parameter, derive from comic:

```python
async def replace_in_library(
    old: ChapterAssignment,
    new: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    source_display_name: str,
) -> None:
    await asyncio.to_thread(
        _replace_in_library_sync,
        old,
        new,
        comic,
        db,
        chapter_name,
        source_display_name,
    )


def _replace_in_library_sync(
    old: ChapterAssignment,
    new: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    source_display_name: str,
) -> None:
    logger.info(
        "replace_in_library: starting upgrade for comic=%r chapter=%r source=%r",
        comic.title,
        chapter_name,
        source_display_name,
    )
    staging = find_staging_path(
        new, comic, chapter_name, source_display_name
    )
```

Update warning logs similarly using `comic.title`.

- [ ] **Step 3: Run linter**

Run: `backend/.venv/bin/ruff check backend/app/services/file_relocator.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/file_relocator.py
git commit -m "refactor: relocate/replace_in_library derive titles from Comic (#169)"
```

---

### Task 3: Update `chapter_event_handler.py` — load aliases, simplify calls

**Files:**
- Modify: `backend/app/workers/chapter_event_handler.py:24-162`

- [ ] **Step 1: Load Comic with aliases eagerly and simplify file_relocator calls**

In `chapter_event_handler.py`, update the Comic load to eagerly fetch aliases:

```python
        comic = await db.execute(
            select(Comic)
            .where(Comic.id == assignment.comic_id)
            .options(selectinload(Comic.aliases))
        )
        comic = comic.scalar_one()
```

Update `file_relocator.relocate()` call — remove `manga_title` parameter:

```python
                await file_relocator.relocate(
                    assignment,
                    comic,
                    db,
                    chapter_name=chapter_name,
                    source_display_name=source_display_name,
                )
```

Update `file_relocator.replace_in_library()` call — remove `manga_title` parameter:

```python
                    await file_relocator.replace_in_library(
                        existing_active,
                        assignment,
                        comic,
                        db,
                        chapter_name=chapter_name,
                        source_display_name=source_display_name,
                    )
```

- [ ] **Step 2: Run existing chapter event handler tests**

Run: `backend/.venv/bin/pytest backend/tests/test_chapter_event_handler.py -v`
Expected: All tests PASS (tests may need updating to match new signatures)

- [ ] **Step 3: Commit**

```bash
git add backend/app/workers/chapter_event_handler.py
git commit -m "feat: chapter_event_handler loads aliases for file_relocator (#169)"
```

---

### Task 4: Fix `requests.py` reprocess — undefined `manga_title` + aliases

**Files:**
- Modify: `backend/app/api/requests.py:665-900`

- [ ] **Step 1: Load Comic with aliases and update all file_relocator calls**

In `reprocess_chapters()`, update the Comic load to include aliases:

```python
        comic_result = await db.execute(
            select(Comic)
            .where(Comic.id == comic_id)
            .options(selectinload(Comic.aliases))
        )
        comic = comic_result.scalar_one_or_none()
```

Remove all `manga_title` variable references. Update `find_staging_path` calls (lines 748, 831):

```python
                staging = file_relocator.find_staging_path(
                    assignment, comic, chapter_name, source_display_name
                )
```

Update `relocate()` calls (lines 768, 849) — remove `manga_title` parameter:

```python
                    await file_relocator.relocate(
                        assignment,
                        comic,
                        db,
                        chapter_name=chapter_name,
                        source_display_name=source_display_name,
                    )
```

Update `replace_in_library()` calls (lines 777, 858) — remove `manga_title` parameter:

```python
                    await file_relocator.replace_in_library(
                        existing_active,
                        assignment,
                        comic,
                        db,
                        chapter_name=chapter_name,
                        source_display_name=source_display_name,
                    )
```

- [ ] **Step 2: Run linter**

Run: `backend/.venv/bin/ruff check backend/app/api/requests.py`
Expected: No new errors

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/requests.py
git commit -m "fix: resolve undefined manga_title in reprocess, use Comic object (#169)"
```

---

### Task 5: Update existing tests to match new signatures

**Files:**
- Modify: `backend/tests/test_file_relocator.py`

- [ ] **Step 1: Update `_make_comic()` helper to support aliases**

Update the helper:

```python
def _make_comic(title="My Comic", library_title="My Comic Library", cover_path=None, aliases=None):
    return SimpleNamespace(
        title=title, library_title=library_title, cover_path=cover_path, aliases=aliases or []
    )
```

- [ ] **Step 2: Update all `find_staging_path()` test calls**

Replace all calls from:
```python
file_relocator.find_staging_path(chapter_name, manga_title, source_display, chapter_number)
```
To:
```python
file_relocator.find_staging_path(assignment, comic, chapter_name, source_display)
```

Each test must create a matching `comic` and `assignment`:
```python
    comic = _make_comic(title=manga_title)
    assignment = _make_assignment(chapter_number=1.0)
    result = file_relocator.find_staging_path(
        assignment, comic, chapter_name, source_display
    )
```

Apply to all affected tests:
- `test_find_staging_path_returns_folder`
- `test_find_staging_path_source_dir_space_stripped`
- `test_find_staging_path_source_dir_with_suffix`
- `test_find_staging_path_source_dir_case_mismatch`
- `test_find_staging_path_source_dir_ambiguous_returns_none`
- `test_find_staging_path_exact_match_skips_fallback`
- `test_find_staging_path_sanitized_*`
- `test_find_staging_path_empty_manga_title_returns_none`
- All `TestFindStagingPathRegex` methods

For `test_find_staging_path_empty_manga_title_returns_none`, use `_make_comic(title="")` — the function should return `None` because the only title is empty.

- [ ] **Step 3: Update `relocate()` and `replace_in_library()` test calls**

Remove `manga_title` parameter from all calls. For example:

```python
# Before:
await file_relocator.relocate(
    assignment, comic, None, chapter_name, manga_title, source_display
)

# After:
await file_relocator.relocate(
    assignment, comic, None, chapter_name, source_display
)
```

- [ ] **Step 4: Run all file relocator tests**

Run: `backend/.venv/bin/pytest backend/tests/test_file_relocator.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `backend/.venv/bin/pytest -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_file_relocator.py
git commit -m "test: update tests for Comic/Assignment-based API (#169)"
```

---

### Task 6: Final verification

**Files:** All modified files

- [ ] **Step 1: Run linter on all modified files**

Run: `backend/.venv/bin/ruff check backend/app/services/file_relocator.py backend/app/workers/chapter_event_handler.py backend/app/api/requests.py`
Expected: No new errors

- [ ] **Step 2: Run full test suite**

Run: `backend/.venv/bin/pytest -v`
Expected: All tests PASS

- [ ] **Step 3: Run integration tests (if .env.test is configured)**

Run: `backend/.venv/bin/pytest -m integration -v`
Expected: Integration tests PASS (or skip if no Suwayomi configured)

- [ ] **Step 4: Stage and commit any remaining changes**

```bash
git add -A
git status
git commit -m "chore: final adjustments for alias folder search (#169)"
```
(Only if there are remaining changes)

---

## Self-Review Checklist

- [x] **Spec coverage:** All spec requirements addressed — `find_staging_path` accepts Comic+Assignment, derives titles from Comic (primary + aliases), caller updates for both `chapter_event_handler` and `requests.py`, test updates, alias tests.
- [x] **Placeholder scan:** No TBD, TODO, or vague instructions. All code blocks are complete.
- [x] **Type consistency:** `find_staging_path(assignment, comic, chapter_name, source_display_name)` used consistently. `relocate()` and `replace_in_library()` both removed `manga_title` parameter.
- [x] **TDD:** Tests written before implementation in Task 1.
- [x] **Frequent commits:** 5 commits mapped to logical boundaries.
