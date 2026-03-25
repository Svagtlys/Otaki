from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.source import Source
from ..models.user import User
from ..services import auth, suwayomi
from ..services.settings import validate_suwayomi, write_env
from .auth import require_auth

router = APIRouter(prefix="/setup", tags=["setup"])


def require_setup_incomplete() -> None:
    if settings.SETUP_COMPLETE:
        raise HTTPException(status_code=409, detail="Setup already complete")


# --- Schemas ---


class ConnectRequest(BaseModel):
    url: str
    username: str
    password: str


class SuwayomiSource(BaseModel):
    id: str
    name: str
    lang: str
    icon_url: str


class SaveSourcesRequest(BaseModel):
    sources: list[SuwayomiSource]


class PathsRequest(BaseModel):
    download_path: str
    library_path: str
    create: bool = False


class CreateUserRequest(BaseModel):
    username: str
    password: str


# --- Endpoints ---


class SetupStatusResponse(BaseModel):
    complete: bool
    admin_created: bool
    suwayomi_url: str | None
    suwayomi_username: str | None
    download_path: str | None
    library_path: str | None


class SetupCompleteResponse(BaseModel):
    complete: bool


@router.get("/complete")
async def setup_complete() -> SetupCompleteResponse:
    return SetupCompleteResponse(complete=settings.SETUP_COMPLETE)


@router.get("/status")
async def setup_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_auth),
) -> SetupStatusResponse:
    count = await db.scalar(select(func.count()).select_from(User))
    return SetupStatusResponse(
        complete=settings.SETUP_COMPLETE,
        admin_created=(count or 0) > 0,
        suwayomi_url=settings.SUWAYOMI_URL,
        suwayomi_username=settings.SUWAYOMI_USERNAME,
        download_path=settings.SUWAYOMI_DOWNLOAD_PATH,
        library_path=settings.LIBRARY_PATH,
    )


@router.post("/user")
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    count = await db.scalar(select(func.count()).select_from(User))
    if count > 0:
        raise HTTPException(status_code=409, detail="Admin user already exists")

    db.add(
        User(
            username=body.username,
            password_hash=auth.hash_password(body.password),
            active=True,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


@router.post("/connect")
async def connect(
    body: ConnectRequest,
    _: None = Depends(require_setup_incomplete),
) -> None:
    ok = await validate_suwayomi(body.url, body.username, body.password)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not connect to Suwayomi")

    write_env("SUWAYOMI_URL", body.url)
    write_env("SUWAYOMI_USERNAME", body.username)
    write_env("SUWAYOMI_PASSWORD", body.password)


@router.get("/sources")
async def get_sources(
    _: None = Depends(require_setup_incomplete),
) -> list[SuwayomiSource]:
    sources = await suwayomi.list_sources()
    return [SuwayomiSource(**s) for s in sources]


@router.post("/sources")
async def save_sources(
    body: SaveSourcesRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_setup_incomplete),
) -> None:
    await db.execute(delete(Source))
    now = datetime.now(timezone.utc)
    for priority, source in enumerate(body.sources, start=1):
        db.add(
            Source(
                suwayomi_source_id=source.id,
                name=source.name,
                priority=priority,
                enabled=True,
                created_at=now,
            )
        )
    await db.commit()


@router.post("/paths")
async def save_paths(
    body: PathsRequest,
    _: None = Depends(require_setup_incomplete),
) -> None:
    from pathlib import Path as FsPath

    fields = (("download_path", body.download_path), ("library_path", body.library_path))

    # First pass: check which directories are missing.
    missing = [
        {"field": field, "path": value}
        for field, value in fields
        if not FsPath(value).is_dir()
    ]
    if missing and not body.create:
        raise HTTPException(
            status_code=400,
            detail={"code": "directories_missing", "missing": missing},
        )

    # Second pass: create any that still don't exist.
    for field, value in fields:
        try:
            FsPath(value).mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Cannot create {field} {value!r}: {exc}"
            )

    write_env("SUWAYOMI_DOWNLOAD_PATH", body.download_path)
    write_env("LIBRARY_PATH", body.library_path)
    write_env("SETUP_COMPLETE", True)
