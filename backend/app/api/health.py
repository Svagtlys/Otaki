import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.source import Source
from ..services import suwayomi
from ..workers import download_listener, scheduler as scheduler_module

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(f"otaki.{__name__}")


class SourceHealth(BaseModel):
    name: str
    enabled: bool
    reachable: bool


class SuwayomiHealth(BaseModel):
    status: str  # "ok" | "unreachable" | "error"
    url: str | None
    sources: list[SourceHealth]


class SchedulerJobHealth(BaseModel):
    comic_id: int
    title: str
    next_poll_at: str | None
    next_upgrade_at: str | None


class SchedulerHealth(BaseModel):
    running: bool
    uptime_seconds: float | None
    jobs: list[SchedulerJobHealth]


class WorkerHealth(BaseModel):
    running: bool
    uptime_seconds: float | None


class WorkersHealth(BaseModel):
    download_listener: WorkerHealth
    scheduler: SchedulerHealth


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    database: str  # "ok" | "error"
    suwayomi: SuwayomiHealth
    workers: WorkersHealth


@router.get("", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    # --- Database ---
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    # --- Suwayomi ---
    from ..config import settings
    suwayomi_url = settings.SUWAYOMI_URL
    source_healths: list[SourceHealth] = []
    suwayomi_status = "unreachable"

    if suwayomi_url:
        try:
            reachable = await suwayomi.ping(
                suwayomi_url,
                settings.SUWAYOMI_USERNAME,
                settings.SUWAYOMI_PASSWORD,
            )
            if reachable:
                suwayomi_status = "ok"
                # Cross-reference DB sources with live Suwayomi sources
                try:
                    live_sources = await suwayomi.list_sources()
                    live_ids = {s["id"] for s in live_sources}
                except Exception:
                    live_ids = set()

                result = await db.execute(select(Source).order_by(Source.priority))
                db_sources = result.scalars().all()
                for src in db_sources:
                    source_healths.append(SourceHealth(
                        name=src.name,
                        enabled=src.enabled,
                        reachable=src.suwayomi_source_id in live_ids,
                    ))
            else:
                suwayomi_status = "unreachable"
        except Exception as exc:
            logger.warning("health: suwayomi check failed: %r", exc)
            suwayomi_status = "error"
    else:
        suwayomi_status = "unreachable"

    # --- Workers ---
    listener_status = download_listener.get_status()
    sched_status = await scheduler_module.get_status(db)

    # --- Overall status ---
    if db_status == "error":
        overall = "unhealthy"
    elif (
        suwayomi_status != "ok"
        or not listener_status["running"]
        or not sched_status["running"]
    ):
        overall = "degraded"
    else:
        overall = "healthy"

    return HealthResponse(
        status=overall,
        database=db_status,
        suwayomi=SuwayomiHealth(
            status=suwayomi_status,
            url=suwayomi_url,
            sources=source_healths,
        ),
        workers=WorkersHealth(
            download_listener=WorkerHealth(**listener_status),
            scheduler=SchedulerHealth(
                running=sched_status["running"],
                uptime_seconds=sched_status["uptime_seconds"],
                jobs=[SchedulerJobHealth(**j) for j in sched_status["jobs"]],
            ),
        ),
    )
