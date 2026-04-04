from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ComicSourcePin(Base):
    __tablename__ = "comic_source_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("comics.id"), nullable=False, index=True
    )
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sources.id"), nullable=False
    )
    suwayomi_manga_id: Mapped[str] = mapped_column(String, nullable=False)
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint(
            "comic_id", "source_id", "suwayomi_manga_id", name="uq_comic_source_pins"
        ),
    )
