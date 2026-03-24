from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..models.user import User
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
