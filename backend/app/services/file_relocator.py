import logging
import os
import re
import shutil
import zipfile
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.chapter_assignment import ChapterAssignment, RelocationStatus
from ..models.comic import Comic
from . import comicinfo_writer

log = logging.getLogger(__name__)


def _find_staging_path(
    chapter_name: str, manga_title: str, source_display_name: str
) -> Path | None:
    base = Path(settings.SUWAYOMI_DOWNLOAD_PATH) / source_display_name / manga_title

    # --- CBZ checks ---
    exact = base / f"{chapter_name}.cbz"
    if exact.exists():
        return exact
    # Fallback 1: only one CBZ in the directory
    matches = list(base.glob("*.cbz"))
    if len(matches) == 1:
        return matches[0]
    # Fallback 2: source prefixes the chapter name (e.g. "Official_Episode 148.cbz"
    # when Suwayomi reports the chapter as "Episode 148"). The pattern anchors to
    # end-of-stem so "Episode 148" does not match "Episode 148.1" or "Episode 1480".
    name_lower = chapter_name.lower()
    pattern = re.compile(re.escape(name_lower) + r"(?:\.\d+)?\s*$")
    containing = [m for m in matches if pattern.search(m.stem.lower())]
    if len(containing) == 1:
        return containing[0]

    # --- Folder checks ---
    # Exact folder name match
    exact_folder = base / chapter_name
    if exact_folder.is_dir():
        return exact_folder
    # Fallback: exactly one subdirectory present
    subdirs = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
    if len(subdirs) == 1:
        return subdirs[0]
    # Prefix match for folders
    folder_containing = [d for d in subdirs if pattern.search(d.name.lower())]
    if len(folder_containing) == 1:
        return folder_containing[0]

    log.warning(
        "file_relocator: ambiguous or missing staging file for chapter %r in %s",
        chapter_name,
        base,
    )
    return None


def _normalize_to_folder(staging: Path) -> Path:
    """Return *staging* as a folder, extracting a CBZ if necessary.

    - If *staging* is already a directory, return it unchanged.
    - If *staging* is a ``.cbz`` file, extract its contents to a sibling
      directory named after the stem, delete the original CBZ, and return
      the extracted folder path.
    """
    if staging.is_dir():
        return staging

    # staging is a CBZ file — extract to a folder with the same stem
    dest_folder = staging.parent / staging.stem
    if dest_folder.exists():
        shutil.rmtree(dest_folder)
    dest_folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(staging, "r") as zf:
        zf.extractall(dest_folder)
    staging.unlink()
    return dest_folder


def _pack_to_cbz(folder: Path) -> Path:
    """Pack *folder* into a ``.cbz`` file and delete the source folder.

    Files are added in alphabetical order of their relative paths, which
    matches Suwayomi's zero-padded page-number naming convention.

    Returns the path of the newly created CBZ.
    """
    cbz_path = folder.parent / (folder.name + ".cbz")
    all_files = sorted(
        (p for p in folder.rglob("*") if p.is_file()),
        key=lambda p: str(p.relative_to(folder)),
    )
    with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for file_path in all_files:
            zf.write(file_path, file_path.relative_to(folder))
    shutil.rmtree(folder)
    return cbz_path


def _render_format(assignment: ChapterAssignment, comic: Comic) -> str:
    fmt = settings.CHAPTER_NAMING_FORMAT

    # Build substitution dict
    title = comic.library_title
    chapter = f"{assignment.chapter_number:06.1f}"
    year = str(assignment.chapter_published_at.year)
    source = assignment.source.name

    if assignment.volume_number is not None:
        volume = f"{assignment.volume_number:02d}"
        rendered = fmt.format(title=title, chapter=chapter, volume=volume, year=year, source=source)
    else:
        # Strip the path segment containing {volume} entirely; if {volume} shares a
        # segment with other tokens, strip only the volume portion inline.
        parts = fmt.split("/")
        cleaned_parts = []
        for p in parts:
            if "{volume}" not in p:
                cleaned_parts.append(p)
            else:
                other_tokens = [t for t in re.findall(r"\{(\w+)\}", p) if t != "volume"]
                if other_tokens:
                    # Inline volume — strip token and surrounding separators/literals
                    p = re.sub(r"[\s\-]*[^\s\-{]*\{volume\}[}\s\-]*", "", p)
                    cleaned_parts.append(p)
                # else: segment is entirely volume-related — drop it
        cleaned = "/".join(cleaned_parts)
        rendered = cleaned.format(title=title, chapter=chapter, year=year, source=source)

    return rendered


def resolve_path(assignment: ChapterAssignment, comic: Comic) -> Path:
    rendered = _render_format(assignment, comic)
    return Path(settings.LIBRARY_PATH) / rendered


def _place_file(staging: Path, dest: Path) -> None:
    """Atomically place staging at dest using the configured strategy, then clean up staging.

    hardlink/auto: os.link to a temp path then os.replace (atomic, no extra disk space).
                   auto falls back to copy+delete if link fails (cross-filesystem).
    copy:          shutil.copy2 to a temp path then os.replace; staging preserved.
    move:          shutil.copy2 to a temp path then os.replace; staging deleted.

    Staging is deleted for all strategies except copy.
    """
    strategy = settings.RELOCATION_STRATEGY
    temp = dest.with_suffix(".tmp")

    if strategy in ("hardlink", "auto"):
        try:
            os.link(staging, temp)
            os.replace(temp, dest)
            staging.unlink(missing_ok=True)
            return
        except OSError:
            temp.unlink(missing_ok=True)
            if strategy == "hardlink":
                raise
            # auto: fall through to copy+delete

    try:
        shutil.copy2(staging, temp)
        assert temp.stat().st_size == staging.stat().st_size
        os.replace(temp, dest)
    except Exception:
        temp.unlink(missing_ok=True)
        raise

    if strategy != "copy":
        staging.unlink(missing_ok=True)


async def relocate(
    assignment: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
) -> None:
    staging = _find_staging_path(chapter_name, manga_title, source_display_name)
    if staging is None:
        assignment.relocation_status = RelocationStatus.failed
        return

    staging = _normalize_to_folder(staging)
    comicinfo_writer.write(staging, comic, assignment)
    staging = _pack_to_cbz(staging)

    dest = resolve_path(assignment, comic)
    dest.parent.mkdir(parents=True, exist_ok=True)

    _place_file(staging, dest)

    assignment.library_path = str(dest)
    assignment.relocation_status = RelocationStatus.done


async def replace_in_library(
    old: ChapterAssignment,
    new: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
) -> None:
    staging = _find_staging_path(chapter_name, manga_title, source_display_name)
    if staging is None:
        new.relocation_status = RelocationStatus.failed
        return

    staging = _normalize_to_folder(staging)
    comicinfo_writer.write(staging, comic, new)
    staging = _pack_to_cbz(staging)

    if old.library_path is None:
        log.warning(
            "replace_in_library: old assignment id=%s has no library_path — skipping upgrade swap",
            old.id,
        )
        new.relocation_status = RelocationStatus.failed
        return

    dest = Path(old.library_path)
    _place_file(staging, dest)

    new.library_path = str(dest)
    new.relocation_status = RelocationStatus.done
    old.relocation_status = RelocationStatus.skipped
