import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .comic import Comic
    from .source import Source


class DownloadStatus(str, enum.Enum):
    queued = "queued"
    downloading = "downloading"
    done = "done"
    failed = "failed"


class RelocationStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class ChapterAssignment(Base):
    __tablename__ = "chapter_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("comics.id"), nullable=False
    )
    chapter_number: Mapped[float] = mapped_column(Float, nullable=False)
    volume_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sources.id"), nullable=False
    )
    suwayomi_manga_id: Mapped[str] = mapped_column(String, nullable=False)
    suwayomi_chapter_id: Mapped[str] = mapped_column(String, nullable=False)
    download_status: Mapped[DownloadStatus] = mapped_column(
        Enum(DownloadStatus, native_enum=False),
        nullable=False,
        default=DownloadStatus.queued,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    chapter_published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    downloaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    library_path: Mapped[str | None] = mapped_column(String, nullable=True)
    relocation_status: Mapped[RelocationStatus] = mapped_column(
        Enum(RelocationStatus, native_enum=False),
        nullable=False,
        default=RelocationStatus.pending,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        Index(
            "ix_chapter_assignments_comic_chapter_active",
            "comic_id",
            "chapter_number",
            "is_active",
        ),
    )

    comic: Mapped["Comic"] = relationship("Comic", back_populates="chapter_assignments")
    source: Mapped["Source"] = relationship(
        "Source", back_populates="chapter_assignments"
    )
