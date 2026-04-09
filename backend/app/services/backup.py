"""Export and import helpers for Otaki backup.

Backup format (version 1):
  backup.json  — full DB snapshot using backup-internal _id references
  covers/      — cover image files named {backup_comic_id}.{ext}

All references within backup.json use _id fields (sequential ints assigned at
export time), not DB surrogate keys.  This makes the file portable across
instances where the same comic may have a different auto-increment id.
"""

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from ..models.comic import Comic
from ..models.comic_alias import ComicAlias
from ..models.comic_source_override import ComicSourceOverride
from ..models.comic_source_pin import ComicSourcePin
from ..models.source import Source

logger = logging.getLogger(f"otaki.{__name__}")

BACKUP_VERSION = 1


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


async def build_backup_json(db: AsyncSession, include_all_assignments: bool = False) -> dict:
    """Build the backup.json dict from the current DB state."""
    sources = (await db.execute(select(Source).order_by(Source.priority))).scalars().all()
    comics = (await db.execute(select(Comic).order_by(Comic.id))).scalars().all()
    aliases = (await db.execute(select(ComicAlias))).scalars().all()
    pins = (await db.execute(select(ComicSourcePin))).scalars().all()
    overrides = (await db.execute(select(ComicSourceOverride))).scalars().all()

    q = select(ChapterAssignment)
    if not include_all_assignments:
        q = q.where(ChapterAssignment.is_active.is_(True))
    assignments = (await db.execute(q)).scalars().all()

    # Build backup-internal id maps
    source_bid: dict[int, int] = {s.id: i + 1 for i, s in enumerate(sources)}
    comic_bid: dict[int, int] = {c.id: i + 1 for i, c in enumerate(comics)}

    def _dt(v: datetime | None) -> str | None:
        return v.isoformat() if v else None

    src_list = [
        {
            "_id": source_bid[s.id],
            "suwayomi_source_id": s.suwayomi_source_id,
            "name": s.name,
            "priority": s.priority,
            "enabled": s.enabled,
        }
        for s in sources
    ]

    comic_list = []
    for c in comics:
        cover_file: str | None = None
        if c.cover_path:
            p = Path(c.cover_path)
            if p.exists():
                cover_file = f"covers/{comic_bid[c.id]}{p.suffix}"
        comic_list.append({
            "_id": comic_bid[c.id],
            "title": c.title,
            "library_title": c.library_title,
            "status": c.status,
            "poll_override_days": c.poll_override_days,
            "upgrade_override_days": c.upgrade_override_days,
            "inferred_cadence_days": c.inferred_cadence_days,
            "created_at": _dt(c.created_at),
            "cover_file": cover_file,
        })

    alias_list = [
        {"comic_id": comic_bid[a.comic_id], "title": a.title}
        for a in aliases
        if a.comic_id in comic_bid
    ]

    pin_list = [
        {
            "comic_id": comic_bid[p.comic_id],
            "source_id": source_bid.get(p.source_id),
            "suwayomi_manga_id": p.suwayomi_manga_id,
        }
        for p in pins
        if p.comic_id in comic_bid and p.source_id in source_bid
    ]

    override_list = [
        {
            "comic_id": comic_bid[o.comic_id],
            "source_id": source_bid[o.source_id],
            "priority_override": o.priority_override,
        }
        for o in overrides
        if o.comic_id in comic_bid and o.source_id in source_bid
    ]

    assignment_list = [
        {
            "comic_id": comic_bid[a.comic_id],
            "source_id": source_bid.get(a.source_id),
            "chapter_number": a.chapter_number,
            "volume_number": a.volume_number,
            "suwayomi_manga_id": a.suwayomi_manga_id,
            "suwayomi_chapter_id": a.suwayomi_chapter_id,
            "download_status": a.download_status,
            "is_active": a.is_active,
            "chapter_published_at": _dt(a.chapter_published_at),
            "downloaded_at": _dt(a.downloaded_at),
            "library_path": a.library_path,
            "relocation_status": a.relocation_status,
            "source_chapter_name": a.source_chapter_name,
            "source_manga_title": a.source_manga_title,
            "retry_count": a.retry_count,
        }
        for a in assignments
        if a.comic_id in comic_bid and a.source_id in source_bid
    ]

    return {
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "include_all_assignments": include_all_assignments,
        "sources": src_list,
        "comics": comic_list,
        "comic_aliases": alias_list,
        "comic_source_pins": pin_list,
        "comic_source_overrides": override_list,
        "chapter_assignments": assignment_list,
    }


async def build_backup_zip(db: AsyncSession, include_all_assignments: bool = False) -> bytes:
    """Return zip archive bytes containing backup.json and covers/."""
    backup = await build_backup_json(db, include_all_assignments)
    comics = (await db.execute(select(Comic).order_by(Comic.id))).scalars().all()
    comic_bid: dict[int, int] = {c.id: i + 1 for i, c in enumerate(comics)}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("backup.json", json.dumps(backup, indent=2, default=str))
        for c in comics:
            if c.cover_path:
                p = Path(c.cover_path)
                if p.exists():
                    arc_name = f"covers/{comic_bid[c.id]}{p.suffix}"
                    zf.write(str(p), arc_name)
    return buf.getvalue()


async def build_backup_csv(db: AsyncSession) -> str:
    """Return CSV string — one row per active ChapterAssignment."""
    import csv
    import io as _io

    assignments = (
        await db.execute(
            select(ChapterAssignment, Comic.title, Comic.library_title, Source.name)
            .join(Comic, ChapterAssignment.comic_id == Comic.id)
            .join(Source, ChapterAssignment.source_id == Source.id)
            .where(ChapterAssignment.is_active.is_(True))
            .order_by(Comic.title, ChapterAssignment.chapter_number)
        )
    ).all()

    out = _io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "comic_title", "library_title", "chapter_number", "volume_number",
        "source_name", "download_status", "relocation_status",
        "library_path", "chapter_published_at",
    ])
    for a, comic_title, library_title, source_name in assignments:
        writer.writerow([
            comic_title,
            library_title,
            a.chapter_number,
            a.volume_number,
            source_name,
            a.download_status,
            a.relocation_status,
            a.library_path or "",
            a.chapter_published_at.isoformat() if a.chapter_published_at else "",
        ])
    return out.getvalue()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def parse_backup_zip(data: bytes) -> tuple[dict, zipfile.ZipFile | None]:
    """Parse zip bytes → (backup_dict, opened_ZipFile).

    The caller is responsible for closing the ZipFile.
    Raises ValueError on malformed input.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError(f"Not a valid zip file: {e}") from e
    try:
        backup = json.loads(zf.read("backup.json"))
    except KeyError:
        zf.close()
        raise ValueError("backup.json not found in zip")
    except json.JSONDecodeError as e:
        zf.close()
        raise ValueError(f"backup.json is not valid JSON: {e}") from e
    return backup, zf


def parse_backup_json(data: bytes) -> dict:
    """Parse raw JSON bytes → backup dict."""
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Not valid JSON: {e}") from e


async def build_preview(backup: dict, db: AsyncSession) -> dict:
    """Diff the backup against the current DB and return a preview dict."""
    # Current DB state
    existing_sources = {
        s.suwayomi_source_id: s
        for s in (await db.execute(select(Source))).scalars().all()
    }
    existing_comics = (await db.execute(select(Comic))).scalars().all()
    existing_titles: dict[str, list[Comic]] = {}
    for c in existing_comics:
        existing_titles.setdefault(c.title, []).append(c)

    source_conflicts = []
    for s in backup.get("sources", []):
        existing = existing_sources.get(s["suwayomi_source_id"])
        if existing and (existing.priority != s["priority"] or existing.enabled != s["enabled"]):
            source_conflicts.append({
                "backup_id": s["_id"],
                "suwayomi_source_id": s["suwayomi_source_id"],
                "name": s["name"],
                "import_priority": s["priority"],
                "import_enabled": s["enabled"],
                "existing_priority": existing.priority,
                "existing_enabled": existing.enabled,
            })

    # Count per backup comic_id
    alias_counts: dict[int, int] = {}
    for a in backup.get("comic_aliases", []):
        alias_counts[a["comic_id"]] = alias_counts.get(a["comic_id"], 0) + 1
    pin_counts: dict[int, int] = {}
    for p in backup.get("comic_source_pins", []):
        pin_counts[p["comic_id"]] = pin_counts.get(p["comic_id"], 0) + 1
    chapter_counts: dict[int, int] = {}
    for ch in backup.get("chapter_assignments", []):
        chapter_counts[ch["comic_id"]] = chapter_counts.get(ch["comic_id"], 0) + 1

    comic_conflicts = []
    new_comics = []
    for c in backup.get("comics", []):
        has_cover = bool(c.get("cover_file"))
        entry = {
            "backup_id": c["_id"],
            "title": c["title"],
            "import_chapters": chapter_counts.get(c["_id"], 0),
            "import_aliases": alias_counts.get(c["_id"], 0),
            "import_pins": pin_counts.get(c["_id"], 0),
            "import_has_cover": has_cover,
        }
        matches = existing_titles.get(c["title"], [])
        if matches:
            for m in matches:
                conflict = dict(entry)
                conflict["existing_id"] = m.id
                conflict["existing_has_cover"] = bool(m.cover_path and Path(m.cover_path).exists())
                comic_conflicts.append(conflict)
        else:
            new_comics.append(entry)

    new_source_bids = {s["_id"] for s in backup.get("sources", [])
                       if s["suwayomi_source_id"] not in existing_sources}
    new_sources = [
        {"backup_id": s["_id"], "suwayomi_source_id": s["suwayomi_source_id"], "name": s["name"]}
        for s in backup.get("sources", [])
        if s["_id"] in new_source_bids
    ]

    totals = {
        "sources": len(backup.get("sources", [])),
        "comics": len(backup.get("comics", [])),
        "chapters": len(backup.get("chapter_assignments", [])),
        "covers": sum(1 for c in backup.get("comics", []) if c.get("cover_file")),
    }

    return {
        "source_conflicts": source_conflicts,
        "comic_conflicts": comic_conflicts,
        "new_sources": new_sources,
        "new_comics": new_comics,
        "totals": totals,
    }


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


async def apply_backup(
    backup: dict,
    zip_data: bytes | None,
    source_resolutions: list[dict],
    comic_resolutions: list[dict],
    db: AsyncSession,
) -> dict:
    """Apply the backup with user-supplied conflict resolutions.

    Returns {"comics": N, "chapters": N, "covers": N, "skipped": N}.
    """
    zf: zipfile.ZipFile | None = None
    if zip_data:
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_data))
        except zipfile.BadZipFile:
            pass

    src_res: dict[int, str] = {r["backup_id"]: r["action"] for r in source_resolutions}
    comic_res: dict[int, dict] = {r["backup_id"]: r for r in comic_resolutions}

    comics_created = 0
    chapters_created = 0
    covers_restored = 0
    skipped = 0

    # --- Sources ---
    existing_sources = {
        s.suwayomi_source_id: s
        for s in (await db.execute(select(Source))).scalars().all()
    }
    # bid → DB Source.id (for resolving chapter_assignments / pins)
    source_db_id: dict[int, int] = {}

    for s in backup.get("sources", []):
        bid = s["_id"]
        existing = existing_sources.get(s["suwayomi_source_id"])
        action = src_res.get(bid, "skip" if existing else "create")

        if existing:
            source_db_id[bid] = existing.id
            if action == "overwrite":
                existing.priority = s["priority"]
                existing.enabled = s["enabled"]
            else:
                skipped += 1
        else:
            # New source — always create
            new_src = Source(
                suwayomi_source_id=s["suwayomi_source_id"],
                name=s["name"],
                priority=s["priority"],
                enabled=s["enabled"],
                created_at=datetime.now(timezone.utc),
            )
            db.add(new_src)
            await db.flush()
            source_db_id[bid] = new_src.id

    # --- Comics ---
    existing_comics_by_id: dict[int, Comic] = {
        c.id: c for c in (await db.execute(select(Comic))).scalars().all()
    }
    comic_db_id: dict[int, int] = {}  # backup _id → target DB comic.id

    for c in backup.get("comics", []):
        bid = c["_id"]
        res = comic_res.get(bid, {})
        action = res.get("action", "skip")

        if action == "skip":
            skipped += 1
            continue

        if action == "merge":
            target_id = res["target_id"]
            comic_db_id[bid] = target_id
            target = existing_comics_by_id.get(target_id)
            if target is None:
                logger.warning("apply_backup: merge target_id=%d not found, skipping", target_id)
                skipped += 1
                continue
            # Cover
            if c.get("cover_file") and zf:
                if res.get("replace_cover") or not (target.cover_path and Path(target.cover_path).exists()):
                    _restore_cover(zf, c["cover_file"], target_id, target)
                    if target.cover_path:
                        covers_restored += 1

        else:  # create
            title = res.get("title_override") or c["title"]
            now = datetime.now(timezone.utc)
            new_comic = Comic(
                title=title,
                library_title=c.get("library_title") or title,
                status=c.get("status", "tracking"),
                poll_override_days=c.get("poll_override_days"),
                upgrade_override_days=c.get("upgrade_override_days"),
                inferred_cadence_days=c.get("inferred_cadence_days"),
                created_at=now,
                next_poll_at=now,
            )
            db.add(new_comic)
            await db.flush()
            comic_db_id[bid] = new_comic.id
            comics_created += 1
            # Cover
            if c.get("cover_file") and zf:
                _restore_cover(zf, c["cover_file"], new_comic.id, new_comic)
                if new_comic.cover_path:
                    covers_restored += 1

    await db.flush()

    # --- Aliases ---
    existing_alias_pairs: set[tuple[int, str]] = {
        (a.comic_id, a.title)
        for a in (await db.execute(select(ComicAlias))).scalars().all()
    }
    for a in backup.get("comic_aliases", []):
        target_comic_id = comic_db_id.get(a["comic_id"])
        if target_comic_id is None:
            continue
        if (target_comic_id, a["title"]) not in existing_alias_pairs:
            db.add(ComicAlias(comic_id=target_comic_id, title=a["title"]))

    # --- Pins ---
    existing_pin_triples: set[tuple[int, int, str]] = {
        (p.comic_id, p.source_id, p.suwayomi_manga_id)
        for p in (await db.execute(select(ComicSourcePin))).scalars().all()
    }
    for p in backup.get("comic_source_pins", []):
        target_comic_id = comic_db_id.get(p["comic_id"])
        target_source_id = source_db_id.get(p.get("source_id", 0))
        if target_comic_id is None or target_source_id is None:
            continue
        triple = (target_comic_id, target_source_id, p["suwayomi_manga_id"])
        if triple not in existing_pin_triples:
            db.add(ComicSourcePin(
                comic_id=target_comic_id,
                source_id=target_source_id,
                suwayomi_manga_id=p["suwayomi_manga_id"],
            ))

    # --- Source overrides ---
    existing_override_pairs: set[tuple[int, int]] = {
        (o.comic_id, o.source_id)
        for o in (await db.execute(select(ComicSourceOverride))).scalars().all()
    }
    for o in backup.get("comic_source_overrides", []):
        target_comic_id = comic_db_id.get(o["comic_id"])
        target_source_id = source_db_id.get(o.get("source_id", 0))
        if target_comic_id is None or target_source_id is None:
            continue
        if (target_comic_id, target_source_id) not in existing_override_pairs:
            db.add(ComicSourceOverride(
                comic_id=target_comic_id,
                source_id=target_source_id,
                priority_override=o["priority_override"],
            ))

    # --- Chapter assignments ---
    existing_chapter_ids: set[tuple[int, str]] = {
        (a.comic_id, a.suwayomi_chapter_id)
        for a in (await db.execute(select(
            ChapterAssignment.comic_id, ChapterAssignment.suwayomi_chapter_id
        ))).all()
    }
    for ch in backup.get("chapter_assignments", []):
        target_comic_id = comic_db_id.get(ch["comic_id"])
        target_source_id = source_db_id.get(ch.get("source_id", 0))
        if target_comic_id is None or target_source_id is None:
            continue
        key = (target_comic_id, ch["suwayomi_chapter_id"])
        if key in existing_chapter_ids:
            skipped += 1
            continue

        def _parse_dt(v: str | None) -> datetime | None:
            if not v:
                return None
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                return None

        db.add(ChapterAssignment(
            comic_id=target_comic_id,
            chapter_number=ch["chapter_number"],
            volume_number=ch.get("volume_number"),
            source_id=target_source_id,
            suwayomi_manga_id=ch["suwayomi_manga_id"],
            suwayomi_chapter_id=ch["suwayomi_chapter_id"],
            download_status=ch.get("download_status", DownloadStatus.done),
            is_active=ch.get("is_active", True),
            chapter_published_at=_parse_dt(ch.get("chapter_published_at")) or datetime.now(timezone.utc),
            downloaded_at=_parse_dt(ch.get("downloaded_at")),
            library_path=ch.get("library_path"),
            relocation_status=ch.get("relocation_status", RelocationStatus.done),
            source_chapter_name=ch.get("source_chapter_name"),
            source_manga_title=ch.get("source_manga_title"),
            retry_count=ch.get("retry_count", 0),
        ))
        chapters_created += 1

    await db.commit()

    if zf:
        zf.close()

    return {
        "comics": comics_created,
        "chapters": chapters_created,
        "covers": covers_restored,
        "skipped": skipped,
    }


def _restore_cover(zf: zipfile.ZipFile, cover_file: str, comic_id: int, comic: Comic) -> None:
    """Extract cover from zip and write to COVERS_PATH/{comic_id}.{ext}."""
    try:
        data = zf.read(cover_file)
    except KeyError:
        logger.warning("apply_backup: cover file %r not found in zip", cover_file)
        return

    ext = Path(cover_file).suffix or ".jpg"
    covers_dir = Path(settings.COVERS_PATH)
    covers_dir.mkdir(parents=True, exist_ok=True)

    # Remove old cover if extension differs
    if comic.cover_path and Path(comic.cover_path).exists():
        old = Path(comic.cover_path)
        if old.suffix != ext:
            old.unlink(missing_ok=True)

    dest = covers_dir / f"{comic_id}{ext}"
    dest.write_bytes(data)
    comic.cover_path = str(dest)
