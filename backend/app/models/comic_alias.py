from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .comic import Comic


class ComicAlias(Base):
    __tablename__ = "comic_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("comics.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)

    comic: Mapped["Comic"] = relationship("Comic", back_populates="aliases")
