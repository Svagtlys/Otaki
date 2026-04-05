import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_db
from ..models.chapter_assignment import (
    ChapterAssignment,
    DownloadStatus,
    RelocationStatus,
)
from ..models.comic import Comic, ComicStatus
from ..models.comic_alias import ComicAlias
from ..models.comic_source_pin import ComicSourcePin
from ..models.source import Source
from ..models.user import User
from ..services import cadence_inferrer, cover_handler, file_relocator, source_selector, suwayomi
from ..workers import scheduler
from .auth import require_auth

logger = logging.getLogger(f"otaki.{__name__}")

router = APIRouter(prefix="/requests", tags=["requests"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SourcePinInput(BaseModel):
    source_id: int
    suwayomi_manga_id: str


class RequestBody(BaseModel):
    primary_title: str
    library_title: str | None = None
    cover_url: str | None = None
    poll_override_days: float | None = None
    upgrade_override_days: float | None = None
    aliases: list[str] = []
    source_pins: list[SourcePinInput] = []


class AliasResponse(BaseModel):
    id: int
    title: str

    model_config = {"from_attributes": True}


class AddAliasBody(BaseModel):
    title: str


class PatchComicBody(BaseModel):
    library_title: str | None = None
    poll_override_days: float | None = None
    upgrade_override_days: float | None = None  # None means "clear"; absent means "unchanged"
    status: ComicStatus | None = None

    model_config = ConfigDict(extra="ignore")


class SourceError(BaseModel):
    source_name: str
    reason: str


class ComicResponse(BaseModel):
    id: int
    title: str
    library_title: str
    cover_url: str | None = Field(None, alias="cover_path")
    status: str
    poll_override_days: float | None
    upgrade_override_days: float | None
    inferred_cadence_days: float | None
    next_poll_at: datetime | None
    next_upgrade_check_at: datetime | None
    last_upgrade_check_at: datetime | None
    created_at: datetime
    aliases: list[AliasResponse] = []

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CreateRequestResponse(ComicResponse):
    source_errors: list[SourceError] = []


class ChapterSummary(BaseModel):
    assignment_id: int
    chapter_number: float
    volume_number: int | None
    source_id: int
    source_name: str
    download_status: str
    is_active: bool
    downloaded_at: datetime | None
    library_path: str | None
    relocation_status: str

    model_config = {"from_attributes": True}


class ComicDetail(ComicResponse):
    chapters: list[ChapterSummary]


class ComicListItem(BaseModel):
    id: int
    title: str
    library_title: str
    status: str
    chapter_counts: dict[str, int]
    poll_override_days: float | None
    upgrade_override_days: float | None
    inferred_cadence_days: float | None
    next_poll_at: datetime | None
    next_upgrade_check_at: datetime | None
    last_upgrade_check_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chapter_summary(a: ChapterAssignment) -> ChapterSummary:
    return ChapterSummary(
        assignment_id=a.id,
        chapter_number=a.chapter_number,
        volume_number=a.volume_number,
        source_id=a.source_id,
        source_name=a.source.name,
        download_status=a.download_status,
        is_active=a.is_active,
        downloaded_at=a.downloaded_at,
        library_path=a.library_path,
        relocation_status=a.relocation_status,
    )


async def _create_assignments_and_enqueue(
    comic_id: int,
    chapter_map: dict,
    db: AsyncSession,
    caller: str,
) -> int:
    """Create ChapterAssignment rows for every entry in *chapter_map* and enqueue downloads.

    Returns the number of assignments created.
    """
    enqueue_by_manga: dict[str, list[str]] = {}
    for ch_num, (source, manga_id, ch_data) in chapter_map.items():
        assignment = ChapterAssignment(
            comic_id=comic_id,
            chapter_number=ch_num,
            volume_number=ch_data.get("volume_number"),
            source_id=source.id,
            suwayomi_manga_id=manga_id,
            suwayomi_chapter_id=ch_data["suwayomi_chapter_id"],
            chapter_published_at=ch_data["chapter_published_at"],
            source_chapter_name=ch_data.get("source_chapter_name"),
            source_manga_title=ch_data.get("source_manga_title"),
            download_status=DownloadStatus.queued,
            is_active=True,
            relocation_status=RelocationStatus.pending,
        )
        db.add(assignment)
        enqueue_by_manga.setdefault(manga_id, []).append(ch_data["suwayomi_chapter_id"])

    for manga_id, chapter_ids in enqueue_by_manga.items():
        try:
            await suwayomi.enqueue_downloads(chapter_ids)
        except Exception as exc:
            logger.warning(
                "%s: enqueue_downloads failed for manga_id=%s: %r",
                caller,
                manga_id,
                exc,
            )

    return len(chapter_map)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=CreateRequestResponse)
async def create_request(
    body: RequestBody,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> CreateRequestResponse:
    # 1. Duplicate check
    existing = await db.execute(select(Comic).where(Comic.title == body.primary_title))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Comic already tracked")

    # 2. Create Comic
    comic = Comic(
        title=body.primary_title,
        library_title=body.library_title or body.primary_title,
        cover_path=None,
        requested_cover_url=body.cover_url or None,
        status=ComicStatus.tracking,
        poll_override_days=body.poll_override_days,  # None = use inferred cadence / default
        upgrade_override_days=body.upgrade_override_days,
        created_at=datetime.now(timezone.utc),
    )
    db.add(comic)
    await db.flush()

    # 2b. Save aliases
    for alias_title in body.aliases:
        db.add(ComicAlias(comic_id=comic.id, title=alias_title))
    if body.aliases:
        await db.flush()

    # 2c. Save source pins
    for pin in body.source_pins:
        db.add(ComicSourcePin(
            comic_id=comic.id,
            source_id=pin.source_id,
            suwayomi_manga_id=pin.suwayomi_manga_id,
        ))
    if body.source_pins:
        await db.flush()

    # 3. Build per-chapter source map and create assignments
    chapter_map, src_errors = await source_selector.build_chapter_source_map(comic, db)
    await _create_assignments_and_enqueue(comic.id, chapter_map, db, "create_request")

    # 4. Infer cadence from chapters (if any were found)
    if chapter_map:
        await db.flush()
        comic.inferred_cadence_days = await cadence_inferrer.infer_cadence(comic.id, db)

    # 5. Set next poll/upgrade times
    effective_poll = comic.poll_override_days or comic.inferred_cadence_days or settings.DEFAULT_POLL_DAYS
    effective_upgrade = comic.upgrade_override_days or comic.inferred_cadence_days or comic.poll_override_days or settings.DEFAULT_POLL_DAYS
    now = datetime.now(timezone.utc)
    comic.next_poll_at = now + timedelta(days=effective_poll)
    comic.next_upgrade_check_at = now + timedelta(days=effective_upgrade)

    # 7. Commit and register jobs
    await db.commit()
    await db.refresh(comic)
    scheduler.register_comic_jobs(comic)

    # 8. Download cover if provided; clear requested_cover_url on success so
    # discover_chapters does not retry a URL that already worked.
    if body.cover_url:
        cover_path = await cover_handler.save_from_url(comic.id, body.cover_url)
        if cover_path:
            comic.cover_path = str(cover_path)
            comic.requested_cover_url = None
            await db.commit()

    # Reload with aliases for response
    result = await db.execute(
        select(Comic).where(Comic.id == comic.id).options(selectinload(Comic.aliases))
    )
    comic = result.scalar_one()

    return CreateRequestResponse(
        **ComicResponse.model_validate(comic).model_dump(),
        source_errors=[SourceError(**e) for e in src_errors],
    )


@router.get("", response_model=list[ComicListItem])
async def list_requests(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> list[ComicListItem]:
    comics_result = await db.execute(select(Comic))
    comics = comics_result.scalars().all()

    if not comics:
        return []

    comic_ids = [c.id for c in comics]

    # Single query: count assignments grouped by (comic_id, download_status)
    counts_result = await db.execute(
        select(
            ChapterAssignment.comic_id,
            ChapterAssignment.download_status,
            func.count().label("n"),
        )
        .where(ChapterAssignment.comic_id.in_(comic_ids))
        .group_by(ChapterAssignment.comic_id, ChapterAssignment.download_status)
    )

    # Build {comic_id: {status: count}}
    counts: dict[int, dict[str, int]] = {c.id: {} for c in comics}
    for comic_id, status, n in counts_result.all():
        counts[comic_id][status] = n

    items = []
    for comic in comics:
        status_counts = counts[comic.id]
        total = sum(status_counts.values())
        chapter_counts = {
            "total": total,
            "done": status_counts.get(DownloadStatus.done, 0),
            "downloading": status_counts.get(DownloadStatus.downloading, 0),
            "queued": status_counts.get(DownloadStatus.queued, 0),
            "failed": status_counts.get(DownloadStatus.failed, 0),
        }
        items.append(
            ComicListItem(
                id=comic.id,
                title=comic.title,
                library_title=comic.library_title,
                status=comic.status,
                chapter_counts=chapter_counts,
                poll_override_days=comic.poll_override_days,
                upgrade_override_days=comic.upgrade_override_days,
                inferred_cadence_days=comic.inferred_cadence_days,
                next_poll_at=comic.next_poll_at,
                next_upgrade_check_at=comic.next_upgrade_check_at,
                last_upgrade_check_at=comic.last_upgrade_check_at,
            )
        )
    return items


@router.get("/{comic_id}", response_model=ComicDetail)
async def get_request(
    comic_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> ComicDetail:
    comic_result = await db.execute(
        select(Comic).where(Comic.id == comic_id).options(selectinload(Comic.aliases))
    )
    comic = comic_result.scalar_one_or_none()
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")

    assignments_result = await db.execute(
        select(ChapterAssignment)
        .where(ChapterAssignment.comic_id == comic_id)
        .options(selectinload(ChapterAssignment.source))
        .order_by(ChapterAssignment.chapter_number)
    )
    assignments = assignments_result.scalars().all()

    return ComicDetail(
        **ComicResponse.model_validate(comic).model_dump(),
        chapters=[_chapter_summary(a) for a in assignments],
    )


@router.patch("/{comic_id}", response_model=ComicResponse)
async def patch_request(
    comic_id: int,
    body: PatchComicBody,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> ComicResponse:
    comic_result = await db.execute(
        select(Comic).where(Comic.id == comic_id).options(selectinload(Comic.aliases))
    )
    comic = comic_result.scalar_one_or_none()
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")

    now = datetime.now(timezone.utc)
    fields = body.model_fields_set

    if "library_title" in fields and body.library_title is not None:
        comic.library_title = body.library_title

    if "poll_override_days" in fields:
        comic.poll_override_days = body.poll_override_days  # None clears the override
        effective_poll = comic.poll_override_days or comic.inferred_cadence_days or settings.DEFAULT_POLL_DAYS
        comic.next_poll_at = now + timedelta(days=effective_poll)

    if "upgrade_override_days" in fields:
        comic.upgrade_override_days = body.upgrade_override_days
        effective_upgrade = comic.upgrade_override_days or comic.inferred_cadence_days or comic.poll_override_days or settings.DEFAULT_POLL_DAYS
        comic.next_upgrade_check_at = now + timedelta(days=effective_upgrade)

    if "status" in fields and body.status is not None:
        old_status = comic.status
        comic.status = body.status
        await db.commit()
        await db.refresh(comic)
        if body.status == ComicStatus.complete:
            scheduler.remove_comic_jobs(comic_id)
        elif body.status == ComicStatus.tracking and old_status != ComicStatus.tracking:
            scheduler.register_comic_jobs(comic)
        result = await db.execute(
            select(Comic).where(Comic.id == comic_id).options(selectinload(Comic.aliases))
        )
        comic = result.scalar_one()
        return ComicResponse.model_validate(comic)

    await db.commit()
    result = await db.execute(
        select(Comic).where(Comic.id == comic_id).options(selectinload(Comic.aliases))
    )
    comic = result.scalar_one()

    if fields & {"poll_override_days", "upgrade_override_days"}:
        scheduler.register_comic_jobs(comic)

    return ComicResponse.model_validate(comic)


class DiscoverResponse(BaseModel):
    new_chapters: int
    source_errors: list[SourceError] = []


@router.post("/{comic_id}/discover", response_model=DiscoverResponse)
async def discover_chapters(
    comic_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> DiscoverResponse:
    """Re-run source discovery for a comic and queue any chapters not yet assigned.

    Intended for comics that ended up with 0 assignments due to a connectivity
    failure at request time. Safe to call at any time — only creates assignments
    for chapter numbers not already tracked with is_active=True.
    """
    comic = await db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")

    chapter_map, src_errors = await source_selector.build_chapter_source_map(comic, db)

    existing_result = await db.execute(
        select(ChapterAssignment.chapter_number).where(
            ChapterAssignment.comic_id == comic_id,
            ChapterAssignment.is_active.is_(True),
        )
    )
    existing_numbers = {row[0] for row in existing_result.all()}

    new_entries = {
        ch_num: entry
        for ch_num, entry in chapter_map.items()
        if ch_num not in existing_numbers
    }

    new_count = await _create_assignments_and_enqueue(
        comic_id, new_entries, db, "discover_chapters"
    )

    # Retry cover download if it was never saved (e.g. sources failed at request time).
    if comic.cover_path is None and comic.requested_cover_url:
        cover_path = await cover_handler.save_from_url(comic.id, comic.requested_cover_url)
        if cover_path:
            comic.cover_path = str(cover_path)
            comic.requested_cover_url = None

    await db.commit()
    return DiscoverResponse(
        new_chapters=new_count,
        source_errors=[SourceError(**e) for e in src_errors],
    )


class ReprocessResponse(BaseModel):
    queued: int
    processed: int
    skipped: int


@router.post("/{comic_id}/reprocess", response_model=ReprocessResponse)
async def reprocess_chapters(
    comic_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> ReprocessResponse:
    """Walk every active chapter through whatever pipeline stage it is stuck in.

    - relocation_status=done, file exists → update_library_file (refreshes
      ComicInfo.xml, cover, and moves to correct path if library_title changed)
    - download_status=queued|downloading → skip (already in progress)
    - download_status=failed → re-enqueue
    - download_status=done, staging file exists → relocate / replace_in_library
    - download_status=done, no staging, file at library_path → update_library_file
    - no staging, no library file → re-enqueue

    Idempotent — safe to call multiple times.
    """
    comic_result = await db.execute(
        select(Comic).where(Comic.id == comic_id)
    )
    comic = comic_result.scalar_one_or_none()
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")

    assignments_result = await db.execute(
        select(ChapterAssignment)
        .where(
            ChapterAssignment.comic_id == comic_id,
            ChapterAssignment.is_active.is_(True),
        )
        .options(selectinload(ChapterAssignment.source))
    )
    assignments = assignments_result.scalars().all()

    # Fetch displayName once — download directories use displayName
    # (e.g. "Webtoons.com (EN)"), not source.name ("Webtoons.com").
    display_name_by_source_id: dict[str, str] = {}
    try:
        for s in await suwayomi.list_sources():
            display_name_by_source_id[s["id"]] = s["display_name"]
    except Exception as exc:
        reason = suwayomi.classify_error(exc)
        logger.warning("reprocess: could not fetch source display names (%s): %r", reason, exc)
        raise HTTPException(
            status_code=503,
            detail=f"Suwayomi is unreachable ({reason}) — reprocess aborted.",
        )

    queued = processed = skipped = 0

    for assignment in assignments:
        chapter_name = assignment.source_chapter_name or f"Chapter {assignment.chapter_number}"
        manga_title = assignment.source_manga_title or comic.title
        source_display_name = display_name_by_source_id.get(
            assignment.source.suwayomi_source_id, assignment.source.name
        )

        # Case 1: already fully relocated — refresh metadata/cover/path
        if (
            assignment.relocation_status == RelocationStatus.done
            and assignment.library_path
            and Path(assignment.library_path).exists()
        ):
            await file_relocator.update_library_file(assignment, comic, db)
            processed += 1
            continue

        # Case 2: already in Suwayomi queue — nothing to do
        if assignment.download_status in (DownloadStatus.queued, DownloadStatus.downloading):
            skipped += 1
            continue

        # Case 3: failed download — re-enqueue
        if assignment.download_status == DownloadStatus.failed:
            assignment.download_status = DownloadStatus.queued
            try:
                await suwayomi.enqueue_downloads([assignment.suwayomi_chapter_id])
            except Exception as exc:
                logger.warning(
                    "reprocess: enqueue_downloads failed for assignment id=%d: %r",
                    assignment.id,
                    exc,
                )
                assignment.download_status = DownloadStatus.failed
            else:
                queued += 1
            continue

        # Case 4: download done — check staging then library
        if assignment.download_status == DownloadStatus.done:
            staging = file_relocator.find_staging_path(
                chapter_name, manga_title, source_display_name
            )
            if staging is not None:
                # Staging file exists — run the normal relocation pipeline
                existing_active = await db.scalar(
                    select(ChapterAssignment).where(
                        ChapterAssignment.comic_id == comic_id,
                        ChapterAssignment.chapter_number == assignment.chapter_number,
                        ChapterAssignment.is_active.is_(True),
                        ChapterAssignment.id != assignment.id,
                    )
                )
                if existing_active is None:
                    await file_relocator.relocate(
                        assignment, comic, db,
                        chapter_name=chapter_name,
                        manga_title=manga_title,
                        source_display_name=source_display_name,
                    )
                else:
                    await file_relocator.replace_in_library(
                        existing_active, assignment, comic, db,
                        chapter_name=chapter_name,
                        manga_title=manga_title,
                        source_display_name=source_display_name,
                    )
                processed += 1
                continue

            # No staging — if library file exists, refresh it
            if assignment.library_path and Path(assignment.library_path).exists():
                await file_relocator.update_library_file(assignment, comic, db)
                processed += 1
                continue

        # Case 5: no staging, no library file — re-enqueue
        assignment.download_status = DownloadStatus.queued
        try:
            await suwayomi.enqueue_downloads([assignment.suwayomi_chapter_id])
        except Exception as exc:
            logger.warning(
                "reprocess: enqueue_downloads failed for assignment id=%d: %r",
                assignment.id,
                exc,
            )
            assignment.download_status = DownloadStatus.failed
        else:
            queued += 1

    await db.commit()
    return ReprocessResponse(queued=queued, processed=processed, skipped=skipped)


@router.get("/{comic_id}/cover")
async def get_cover(
    comic_id: int,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    comic = await db.get(Comic, comic_id)
    if comic is None or not comic.cover_path:
        raise HTTPException(status_code=404, detail="Cover not found")
    cover = Path(comic.cover_path)
    if not cover.exists():
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(str(cover))


@router.post("/{comic_id}/cover")
async def set_cover(
    comic_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
    file: UploadFile | None = File(default=None),
) -> dict:
    comic = await db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")

    if file is not None:
        # Multipart upload
        if not (file.content_type or "").startswith("image/"):
            raise HTTPException(status_code=415, detail="File must be an image")
        content = await file.read()
        cover_path = cover_handler.save_from_file(
            comic_id, content, file.content_type or "image/jpeg"
        )
        if cover_path is None:
            raise HTTPException(status_code=415, detail="File must be an image")
    else:
        # JSON body with URL
        body = await request.json()
        url = body.get("url")
        if not url:
            raise HTTPException(status_code=422, detail="url is required")
        cover_path = await cover_handler.save_from_url(comic_id, url)
        if cover_path is None:
            raise HTTPException(status_code=502, detail="Cover download failed")

    # Remove previous cover file if it differs from the new one
    if comic.cover_path and comic.cover_path != str(cover_path):
        Path(comic.cover_path).unlink(missing_ok=True)

    comic.cover_path = str(cover_path)
    await db.commit()
    return {"cover_url": f"/api/requests/{comic_id}/cover"}


@router.delete("/{comic_id}/cover", status_code=204)
async def delete_cover(
    comic_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> Response:
    comic = await db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")
    if comic.cover_path:
        Path(comic.cover_path).unlink(missing_ok=True)
        comic.cover_path = None
        await db.commit()
    return Response(status_code=204)


@router.get("/{comic_id}/aliases", response_model=list[AliasResponse])
async def list_aliases(
    comic_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> list[AliasResponse]:
    comic = await db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")
    result = await db.execute(select(ComicAlias).where(ComicAlias.comic_id == comic_id))
    return [AliasResponse.model_validate(a) for a in result.scalars().all()]


@router.post("/{comic_id}/aliases", status_code=201, response_model=AliasResponse)
async def add_alias(
    comic_id: int,
    body: AddAliasBody,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> AliasResponse:
    comic = await db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")
    alias = ComicAlias(comic_id=comic_id, title=body.title)
    db.add(alias)
    await db.commit()
    await db.refresh(alias)
    return AliasResponse.model_validate(alias)


@router.delete("/{comic_id}/aliases/{alias_id}", status_code=204)
async def delete_alias(
    comic_id: int,
    alias_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> Response:
    alias = await db.get(ComicAlias, alias_id)
    if alias is None or alias.comic_id != comic_id:
        raise HTTPException(status_code=404, detail="Alias not found")
    await db.delete(alias)
    await db.commit()
    return Response(status_code=204)


class SourcePinResponse(BaseModel):
    id: int
    source_id: int
    source_name: str
    suwayomi_manga_id: str
    pinned_at: datetime


class PutPinsBody(BaseModel):
    pins: list[SourcePinInput]


@router.get("/{comic_id}/pins", response_model=list[SourcePinResponse])
async def list_pins(
    comic_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> list[SourcePinResponse]:
    comic = await db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")

    result = await db.execute(
        select(ComicSourcePin, Source.name.label("source_name"))
        .join(Source, ComicSourcePin.source_id == Source.id)
        .where(ComicSourcePin.comic_id == comic_id)
        .order_by(ComicSourcePin.source_id, ComicSourcePin.suwayomi_manga_id)
    )
    rows = result.all()
    return [
        SourcePinResponse(
            id=pin.id,
            source_id=pin.source_id,
            source_name=source_name,
            suwayomi_manga_id=pin.suwayomi_manga_id,
            pinned_at=pin.pinned_at,
        )
        for pin, source_name in rows
    ]


@router.put("/{comic_id}/pins", response_model=list[SourcePinResponse])
async def replace_pins(
    comic_id: int,
    body: PutPinsBody,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> list[SourcePinResponse]:
    comic = await db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")

    # Delete all existing pins for this comic
    await db.execute(
        delete(ComicSourcePin).where(ComicSourcePin.comic_id == comic_id)
    )

    # Insert new pins
    for pin in body.pins:
        db.add(ComicSourcePin(
            comic_id=comic_id,
            source_id=pin.source_id,
            suwayomi_manga_id=pin.suwayomi_manga_id,
        ))

    await db.commit()

    # Return the new state
    result = await db.execute(
        select(ComicSourcePin, Source.name.label("source_name"))
        .join(Source, ComicSourcePin.source_id == Source.id)
        .where(ComicSourcePin.comic_id == comic_id)
        .order_by(ComicSourcePin.source_id, ComicSourcePin.suwayomi_manga_id)
    )
    rows = result.all()
    return [
        SourcePinResponse(
            id=pin.id,
            source_id=pin.source_id,
            source_name=source_name,
            suwayomi_manga_id=pin.suwayomi_manga_id,
            pinned_at=pin.pinned_at,
        )
        for pin, source_name in rows
    ]


@router.delete("/{comic_id}", status_code=204)
async def delete_request(
    comic_id: int,
    delete_files: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> None:
    comic = await db.get(Comic, comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="Comic not found")

    assignments_result = await db.execute(
        select(ChapterAssignment).where(ChapterAssignment.comic_id == comic_id)
    )
    assignments = assignments_result.scalars().all()

    if delete_files:
        for a in assignments:
            if a.library_path:
                Path(a.library_path).unlink(missing_ok=True)

    scheduler.remove_comic_jobs(comic_id)

    await db.execute(
        delete(ChapterAssignment).where(ChapterAssignment.comic_id == comic_id)
    )
    await db.delete(comic)
    await db.commit()
