from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.source import Source
from ..models.user import User
from .auth import require_auth

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceResponse(BaseModel):
    id: int
    suwayomi_source_id: str
    name: str
    priority: int
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PatchSourceRequest(BaseModel):
    name: str | None = None
    priority: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> list[SourceResponse]:
    result = await db.execute(select(Source).order_by(Source.priority))
    return result.scalars().all()


@router.patch("/{source_id}", response_model=SourceResponse)
async def patch_source(
    source_id: int,
    body: PatchSourceRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
) -> SourceResponse:
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if body.name is not None:
        source.name = body.name
    if body.priority is not None:
        source.priority = body.priority
    if body.enabled is not None:
        source.enabled = body.enabled

    await db.commit()
    await db.refresh(source)
    return source
