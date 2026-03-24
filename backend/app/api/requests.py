import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_db
from ..models.chapter_assignment import ChapterAssignment, DownloadStatus, RelocationStatus
from ..models.comic import Comic, ComicStatus
from ..models.user import User
from ..services import source_selector, suwayomi
from ..workers import scheduler
from .auth import require_auth

log = logging.getLogger(__name__)

router = APIRouter(prefix="/requests", tags=["requests"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RequestBody(BaseModel):
    primary_title: str
    library_title: str | None = None
    cover_url: str | None = None
    poll_override_days: float | None = None
    upgrade_override_days: float | None = None


class ComicResponse(BaseModel):
    id: int
    title: str
    library_title: str
    cover_url: str | None = Field(None, alias="cover_path")
    status: str
    poll_override_days: float
    upgrade_override_days: float | None
    next_poll_at: datetime | None
    next_upgrade_check_at: datetime | None
    last_upgrade_check_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


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
    poll_override_days: float
    upgrade_override_days: float | None
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=ComicResponse)
async def create_request(
    body: RequestBody,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> ComicResponse:
    # 1. Duplicate check
    existing = await db.execute(select(Comic).where(Comic.title == body.primary_title))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Comic already tracked")

    # 2. Create Comic
    poll_days = body.poll_override_days or settings.DEFAULT_POLL_DAYS
    upgrade_days = body.upgrade_override_days
    comic = Comic(
        title=body.primary_title,
        library_title=body.library_title or body.primary_title,
        cover_path=None,
        status=ComicStatus.tracking,
        poll_override_days=poll_days,
        upgrade_override_days=upgrade_days,
        created_at=datetime.now(timezone.utc),
    )
    db.add(comic)
    await db.flush()

    # 3. Build per-chapter source map
    chapter_map = await source_selector.build_chapter_source_map(comic, db)

    # 4. Group by (source_id, manga_id) to batch fetch_chapters calls
    groups: dict[tuple[int, str], list[float]] = {}
    for ch_num, (source, manga_id) in chapter_map.items():
        groups.setdefault((source.id, manga_id), []).append(ch_num)

    # 5. Fetch chapters and create assignments
    for (source_id, manga_id), ch_nums in groups.items():
        try:
            fetched = await suwayomi.fetch_chapters(manga_id)
        except Exception as exc:
            log.warning("create_request: fetch_chapters failed for manga_id=%s: %r", manga_id, exc)
            continue

        fetched_by_num = {ch["chapter_number"]: ch for ch in fetched}
        chapter_ids_to_enqueue: list[str] = []

        for ch_num in ch_nums:
            ch_data = fetched_by_num.get(ch_num)
            if ch_data is None:
                log.warning(
                    "create_request: chapter %.1f not in fetch result for manga_id=%s",
                    ch_num,
                    manga_id,
                )
                continue

            assignment = ChapterAssignment(
                comic_id=comic.id,
                chapter_number=ch_num,
                volume_number=ch_data.get("volume_number"),
                source_id=source_id,
                suwayomi_manga_id=manga_id,
                suwayomi_chapter_id=ch_data["suwayomi_chapter_id"],
                chapter_published_at=ch_data["chapter_published_at"],
                download_status=DownloadStatus.queued,
                is_active=True,
                relocation_status=RelocationStatus.pending,
            )
            db.add(assignment)
            chapter_ids_to_enqueue.append(ch_data["suwayomi_chapter_id"])

        if chapter_ids_to_enqueue:
            try:
                await suwayomi.enqueue_downloads(chapter_ids_to_enqueue)
            except Exception as exc:
                log.warning(
                    "create_request: enqueue_downloads failed for manga_id=%s: %r",
                    manga_id,
                    exc,
                )

    # 6. Set next poll/upgrade times
    now = datetime.now(timezone.utc)
    comic.next_poll_at = now + timedelta(days=poll_days)
    comic.next_upgrade_check_at = now + timedelta(days=upgrade_days or poll_days)

    # 7. Commit and register jobs
    await db.commit()
    await db.refresh(comic)
    scheduler.register_comic_jobs(comic)

    return ComicResponse.model_validate(comic)


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
    comic = await db.get(Comic, comic_id)
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
