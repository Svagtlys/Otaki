import asyncio
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
from . import comicinfo_writer, cover_handler

logger = logging.getLogger(f"otaki.{__name__}")


def _normalize_source_name(name: str) -> str:
    """Lowercase and strip all non-alphanumeric characters for fuzzy directory matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _title_regex(title: str) -> re.Pattern:
    """Build a regex where each special char in *title* matches any one special char.

    Letters, digits, and whitespace match literally.  Any other character
    (e.g. ':') becomes ``[^a-zA-Z0-9]`` so it matches whatever single
    substitution Suwayomi applied on disk (e.g. '_' or ' ').
    """
    parts = []
    for ch in title:
        if re.match(r"[a-zA-Z0-9\s]", ch):
            parts.append(re.escape(ch))
        else:
            parts.append(r"[^a-zA-Z0-9]")
    return re.compile(r"^" + "".join(parts) + r"$")


def _find_manga_subdir(source_dir: Path, manga_title: str) -> Path | None:
    """Return the manga subdirectory inside *source_dir*, tolerating sanitized names.

    Tries exact match first, then falls back to regex match (one special char
    in title matches any one special char on disk).  Returns ``None`` if zero
    or multiple directories match.
    """
    exact = source_dir / manga_title
    if exact.is_dir():
        return exact
    if not source_dir.is_dir():
        return None
    pattern = _title_regex(manga_title)
    matches = [d for d in source_dir.iterdir() if d.is_dir() and pattern.match(d.name)]
    if len(matches) == 1:
        logger.warning(
            "file_relocator: manga dir %r not found; using sanitized match %r",
            manga_title,
            matches[0].name,
        )
        return matches[0]
    if len(matches) > 1:
        logger.warning(
            "file_relocator: ambiguous manga directory for title %r — matches: %s",
            manga_title,
            [d.name for d in matches],
        )
    return None


def find_staging_path(
    chapter_name: str, manga_title: str, source_display_name: str
) -> Path | None:
    source_dir = Path(settings.SUWAYOMI_DOWNLOAD_PATH) / source_display_name
    base = _find_manga_subdir(source_dir, manga_title)

    if base is None:
        # Fuzzy fallback: scan SUWAYOMI_DOWNLOAD_PATH for a source directory whose
        # normalised name starts with the normalised display name. This handles cases
        # like displayName="Weeb Central" but on-disk dir="WeebCentral" or
        # "Weeb Central (EN)". Also handles sanitized manga subdirectory names.
        download_root = Path(settings.SUWAYOMI_DOWNLOAD_PATH)
        norm_display = _normalize_source_name(source_display_name)
        candidates = [
            d for d in download_root.iterdir()
            if d.is_dir() and _normalize_source_name(d.name).startswith(norm_display)
            and _find_manga_subdir(d, manga_title) is not None
        ]
        if len(candidates) == 1:
            logger.warning(
                "file_relocator: source dir %r not found; using fuzzy match %r for display name %r",
                source_display_name,
                candidates[0].name,
                source_display_name,
            )
            base = _find_manga_subdir(candidates[0], manga_title)
        elif len(candidates) > 1:
            logger.warning(
                "file_relocator: ambiguous source directory for display name %r — "
                "multiple fuzzy matches: %s",
                source_display_name,
                [d.name for d in candidates],
            )
            return None

    if base is None:
        base = source_dir / manga_title  # non-existent path; triggers warning at end

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

    logger.warning(
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
        key=lambda p: (
            0 if p.name.lower().startswith("cover.") else 1,
            str(p.relative_to(folder)),
        ),
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
        rendered = fmt.format(
            title=title, chapter=chapter, volume=volume, year=year, source=source
        )
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
        rendered = cleaned.format(
            title=title, chapter=chapter, year=year, source=source
        )

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
    logger.info(
        "relocate: starting for comic=%r chapter=%r source=%r",
        manga_title,
        chapter_name,
        source_display_name,
    )
    staging = find_staging_path(chapter_name, manga_title, source_display_name)
    if staging is None:
        logger.warning(
            "relocate: no staging file found for comic=%r chapter=%r source=%r — marking failed",
            manga_title,
            chapter_name,
            source_display_name,
        )
        assignment.relocation_status = RelocationStatus.failed
        return

    logger.info("relocate: staging path resolved to %s", staging)
    staging = _normalize_to_folder(staging)
    comicinfo_writer.write(staging, comic, assignment)
    cover_handler.inject(staging, comic)
    staging = _pack_to_cbz(staging)

    dest = resolve_path(assignment, comic)
    dest.parent.mkdir(parents=True, exist_ok=True)

    logger.info("relocate: placing %s -> %s", staging, dest)
    _place_file(staging, dest)

    assignment.library_path = str(dest)
    assignment.relocation_status = RelocationStatus.done
    logger.info(
        "relocate: done for comic=%r chapter=%r -> %s", manga_title, chapter_name, dest
    )


async def replace_in_library(
    old: ChapterAssignment,
    new: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
    chapter_name: str,
    manga_title: str,
    source_display_name: str,
) -> None:
    logger.info(
        "replace_in_library: starting upgrade for comic=%r chapter=%r source=%r",
        manga_title,
        chapter_name,
        source_display_name,
    )
    staging = find_staging_path(chapter_name, manga_title, source_display_name)
    if staging is None:
        logger.warning(
            "replace_in_library: no staging file found for comic=%r chapter=%r source=%r — marking failed",
            manga_title,
            chapter_name,
            source_display_name,
        )
        new.relocation_status = RelocationStatus.failed
        return

    logger.info("replace_in_library: staging path resolved to %s", staging)
    staging = _normalize_to_folder(staging)
    comicinfo_writer.write(staging, comic, new)
    cover_handler.inject(staging, comic)
    staging = _pack_to_cbz(staging)

    if old.library_path is None:
        logger.warning(
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


async def update_library_file(
    assignment: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
) -> None:
    """Re-process a chapter that is already in the library.

    Extracts the existing CBZ, rewrites ``ComicInfo.xml`` and the cover to
    reflect the current ``comic.library_title`` and ``comic.cover_path``,
    repacks, and moves the file to the canonical path derived from the
    current ``library_title`` (in case it has changed since original relocation).

    Updates ``assignment.library_path`` if the file was moved.
    No-ops silently if ``assignment.library_path`` is unset or the file is missing.
    """
    if not assignment.library_path:
        logger.warning(
            "update_library_file: assignment id=%d has no library_path — skipping",
            assignment.id,
        )
        return

    current = Path(assignment.library_path)
    if not current.exists():
        logger.warning(
            "update_library_file: library file not found at %s — skipping",
            current,
        )
        return

    logger.info("update_library_file: processing %s", current)

    # Extract, update metadata and cover, repack.
    folder = _normalize_to_folder(current)
    comicinfo_writer.write(folder, comic, assignment)
    cover_handler.inject(folder, comic)
    packed = _pack_to_cbz(folder)

    # Resolve expected destination based on current library_title.
    dest = resolve_path(assignment, comic)

    if dest == current:
        # Path unchanged — replace in-place atomically.
        os.replace(packed, dest)
    else:
        # library_title changed — move to new path, clean up old.
        dest.parent.mkdir(parents=True, exist_ok=True)
        _place_file(packed, dest)
        current.unlink(missing_ok=True)
        assignment.library_path = str(dest)

    logger.info("update_library_file: done — %s", dest)
