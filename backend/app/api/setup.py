from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.source import Source
from ..models.user import User
from ..services import auth, suwayomi

router = APIRouter(prefix="/setup", tags=["setup"])


def _write_env(key: str, value: str) -> None:
    from dotenv import set_key

    set_key(".env", key, value)


def require_setup_incomplete() -> None:
    if (
        settings.SUWAYOMI_URL is not None
        and settings.SUWAYOMI_DOWNLOAD_PATH is not None
        and settings.LIBRARY_PATH is not None
    ):
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


class CreateUserRequest(BaseModel):
    username: str
    password: str


# --- Endpoints ---


@router.post("/user")
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_setup_incomplete),
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
    ok = await suwayomi.ping(body.url, body.username, body.password)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not connect to Suwayomi")

    _write_env("SUWAYOMI_URL", body.url)
    _write_env("SUWAYOMI_USERNAME", body.username)
    _write_env("SUWAYOMI_PASSWORD", body.password)
    settings.SUWAYOMI_URL = body.url
    settings.SUWAYOMI_USERNAME = body.username
    settings.SUWAYOMI_PASSWORD = body.password


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
    for field, value in (
        ("download_path", body.download_path),
        ("library_path", body.library_path),
    ):
        if not Path(value).is_dir():
            raise HTTPException(
                status_code=400, detail=f"Invalid {field}: {value!r} is not a directory"
            )

    _write_env("SUWAYOMI_DOWNLOAD_PATH", body.download_path)
    _write_env("LIBRARY_PATH", body.library_path)
    settings.SUWAYOMI_DOWNLOAD_PATH = body.download_path
    settings.LIBRARY_PATH = body.library_path
