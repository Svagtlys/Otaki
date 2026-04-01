import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..config import settings
from ..database import Base

if TYPE_CHECKING:
    from .chapter_assignment import ChapterAssignment
    from .comic_alias import ComicAlias


class ComicStatus(str, enum.Enum):
    tracking = "tracking"
    complete = "complete"


class Comic(Base):
    __tablename__ = "comics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    library_title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ComicStatus] = mapped_column(
        Enum(ComicStatus, native_enum=False),
        nullable=False,
        default=ComicStatus.tracking,
    )
    poll_override_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    upgrade_override_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    inferred_cadence_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_upgrade_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_upgrade_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    chapter_assignments: Mapped[list["ChapterAssignment"]] = relationship(
        "ChapterAssignment", back_populates="comic"
    )
    aliases: Mapped[list["ComicAlias"]] = relationship(
        "ComicAlias", back_populates="comic", cascade="all, delete-orphan"
    )
