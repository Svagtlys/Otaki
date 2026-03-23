# Stub — full implementation in issue #14.
# chapter_event_handler imports this module; the real logic (hardlink/copy, atomic
# upgrade swap) will replace these stubs when #14 lands.

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chapter_assignment import ChapterAssignment
from ..models.comic import Comic


async def relocate(
    assignment: ChapterAssignment, comic: Comic, db: AsyncSession
) -> None:
    raise NotImplementedError("file_relocator.relocate is implemented in #14")


async def replace_in_library(
    old: ChapterAssignment,
    new: ChapterAssignment,
    comic: Comic,
    db: AsyncSession,
) -> None:
    raise NotImplementedError("file_relocator.replace_in_library is implemented in #14")
