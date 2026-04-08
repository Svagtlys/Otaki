import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.user import User
from ..services import backup as backup_svc
from ..services.settings import validate_path, validate_suwayomi, write_env
from .auth import require_auth

router = APIRouter(prefix="/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
    suwayomi_url: str | None
    suwayomi_username: str | None
    suwayomi_password: str | None  # "**masked**" if set, None if not
    suwayomi_download_path: str | None
    library_path: str | None
    default_poll_days: int
    chapter_naming_format: str
    relocation_strategy: str


class SettingsPatch(BaseModel):
    suwayomi_url: str | None = None
    suwayomi_username: str | None = None
    suwayomi_password: str | None = None  # None = leave unchanged
    suwayomi_download_path: str | None = None
    library_path: str | None = None
    default_poll_days: int | None = None
    chapter_naming_format: str | None = None
    relocation_strategy: Literal["auto", "hardlink", "copy", "move"] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_response() -> SettingsResponse:
    return SettingsResponse(
        suwayomi_url=settings.SUWAYOMI_URL,
        suwayomi_username=settings.SUWAYOMI_USERNAME,
        suwayomi_password="**masked**" if settings.SUWAYOMI_PASSWORD else None,
        suwayomi_download_path=settings.SUWAYOMI_DOWNLOAD_PATH,
        library_path=settings.LIBRARY_PATH,
        default_poll_days=settings.DEFAULT_POLL_DAYS,
        chapter_naming_format=settings.CHAPTER_NAMING_FORMAT,
        relocation_strategy=settings.RELOCATION_STRATEGY,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=SettingsResponse)
async def get_settings(
    _user: User = Depends(require_auth),
) -> SettingsResponse:
    return _build_response()


@router.patch("", response_model=SettingsResponse)
async def patch_settings(
    body: SettingsPatch,
    _user: User = Depends(require_auth),
) -> SettingsResponse:
    provided = body.model_fields_set

    # Validate Suwayomi connectivity if any connection field is being changed
    suwayomi_fields = {"suwayomi_url", "suwayomi_username", "suwayomi_password"}
    if provided & suwayomi_fields:
        test_url = body.suwayomi_url if body.suwayomi_url is not None else settings.SUWAYOMI_URL
        test_username = body.suwayomi_username if body.suwayomi_username is not None else settings.SUWAYOMI_USERNAME
        test_password = body.suwayomi_password if body.suwayomi_password is not None else settings.SUWAYOMI_PASSWORD
        if test_url:
            ok = await validate_suwayomi(test_url, test_username, test_password)
            if not ok:
                raise HTTPException(status_code=400, detail="Could not connect to Suwayomi")

    # Validate paths before writing
    if body.suwayomi_download_path is not None and not validate_path(body.suwayomi_download_path):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid suwayomi_download_path: {body.suwayomi_download_path!r} is not a directory",
        )
    if body.library_path is not None and not validate_path(body.library_path):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid library_path: {body.library_path!r} is not a directory",
        )

    # Apply updates
    field_map = {
        "suwayomi_url": "SUWAYOMI_URL",
        "suwayomi_username": "SUWAYOMI_USERNAME",
        "suwayomi_password": "SUWAYOMI_PASSWORD",
        "suwayomi_download_path": "SUWAYOMI_DOWNLOAD_PATH",
        "library_path": "LIBRARY_PATH",
        "default_poll_days": "DEFAULT_POLL_DAYS",
        "chapter_naming_format": "CHAPTER_NAMING_FORMAT",
        "relocation_strategy": "RELOCATION_STRATEGY",
    }
    for field, env_key in field_map.items():
        if field in provided:
            value = getattr(body, field)
            if value is not None:
                write_env(env_key, value)

    return _build_response()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.get("/export")
async def export_backup(
    format: Literal["otaki", "json", "csv"] = Query(default="otaki"),
    include_all_assignments: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> Response:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if format == "otaki":
        data = await backup_svc.build_backup_zip(db, include_all_assignments)
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="otaki-backup-{date_str}.zip"'},
        )

    if format == "json":
        data = await backup_svc.build_backup_json(db, include_all_assignments)
        return Response(
            content=json.dumps(data, indent=2, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="otaki-backup-{date_str}.json"'},
        )

    # csv
    data = await backup_svc.build_backup_csv(db)
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="otaki-backup-{date_str}.csv"'},
    )


# ---------------------------------------------------------------------------
# Import — preview
# ---------------------------------------------------------------------------


@router.post("/import/preview")
async def import_preview(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
    file: UploadFile | None = File(default=None),
    path: str | None = Form(default=None),
) -> dict:
    """Parse a backup zip (or JSON) and return a conflict/new preview without writing to the DB."""
    raw = await _load_backup_bytes(file, path)
    try:
        backup, zf = backup_svc.parse_backup_zip(raw)
        if zf:
            zf.close()
    except ValueError:
        try:
            backup = backup_svc.parse_backup_json(raw)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    return await backup_svc.build_preview(backup, db)


# ---------------------------------------------------------------------------
# Import — apply
# ---------------------------------------------------------------------------


class SourceResolution(BaseModel):
    backup_id: int
    action: Literal["overwrite", "skip"]


class ComicResolution(BaseModel):
    backup_id: int
    action: Literal["merge", "create", "skip"]
    target_id: int | None = None
    title_override: str | None = None
    replace_cover: bool = False


class ApplySummary(BaseModel):
    comics: int
    chapters: int
    covers: int
    skipped: int


@router.post("/import/apply", response_model=ApplySummary)
async def import_apply(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
    file: UploadFile | None = File(default=None),
    path: str | None = Form(default=None),
    source_resolutions: str = Form(default="[]"),
    comic_resolutions: str = Form(default="[]"),
) -> ApplySummary:
    """Apply a backup zip with user-supplied conflict resolutions."""
    raw = await _load_backup_bytes(file, path)

    try:
        src_res = [SourceResolution(**r).model_dump() for r in json.loads(source_resolutions)]
        com_res = [ComicResolution(**r).model_dump() for r in json.loads(comic_resolutions)]
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid resolutions: {e}")

    try:
        backup, zf = backup_svc.parse_backup_zip(raw)
        if zf:
            zf.close()
        zip_data: bytes | None = raw
    except ValueError:
        try:
            backup = backup_svc.parse_backup_json(raw)
            zip_data = None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    result = await backup_svc.apply_backup(backup, zip_data, src_res, com_res, db)
    return ApplySummary(**result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_backup_bytes(file: UploadFile | None, path: str | None) -> bytes:
    if file is not None:
        return await file.read()
    if path:
        p = Path(path)
        if not p.exists():
            raise HTTPException(status_code=422, detail=f"File not found: {path}")
        return p.read_bytes()
    raise HTTPException(status_code=422, detail="Provide a file upload or a server path")
