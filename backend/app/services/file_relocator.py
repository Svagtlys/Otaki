import logging
import os
import re
import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.chapter_assignment import ChapterAssignment, RelocationStatus
from ..models.comic import Comic

log = logging.getLogger(__name__)


def _find_staging_path(
    chapter_name: str, manga_title: str, source_display_name: str
) -> Path | None:
    base = Path(settings.SUWAYOMI_DOWNLOAD_PATH) / source_display_name / manga_title
    exact = base / f"{chapter_name}.cbz"
    if exact.exists():
        return exact
    # Fallback: OS may have sanitised the filename
    matches = list(base.glob("*.cbz"))
    if len(matches) == 1:
        return matches[0]
    log.warning(
        "file_relocator: ambiguous or missing staging file for chapter %r in %s",
        chapter_name,
        base,
    )
    return None


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

    dest = Path(old.library_path)
    _place_file(staging, dest)

    new.library_path = str(dest)
    new.relocation_status = RelocationStatus.done
    old.relocation_status = RelocationStatus.skipped
