import logging
import statistics
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chapter_assignment import ChapterAssignment

logger = logging.getLogger(f"otaki.{__name__}")


async def infer_cadence(comic_id: int, db: AsyncSession) -> float | None:
    """Return the inferred release cadence in days for a comic, or None if insufficient data.

    Algorithm:
    1. Collect chapter_published_at timestamps for all active chapters, sorted ascending.
    2. Compute gaps (in days) between consecutive chapters.
    3. Calculate initial median of all gaps.
    4. Discard gaps > 3× initial median (hiatus filter).
    5. Return the filtered median, or None if fewer than 2 chapters exist.
    """
    result = await db.execute(
        select(ChapterAssignment.chapter_published_at)
        .where(
            ChapterAssignment.comic_id == comic_id,
            ChapterAssignment.is_active.is_(True),
        )
        .order_by(ChapterAssignment.chapter_published_at)
    )
    timestamps = [row[0] for row in result.all()]

    if len(timestamps) < 2:
        return None

    # Ensure all timestamps are timezone-aware for consistent subtraction
    aware = [
        ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
        for ts in timestamps
    ]

    gaps = [(aware[i + 1] - aware[i]).total_seconds() / 86400.0 for i in range(len(aware) - 1)]

    # Filter zero or negative gaps (duplicate upload dates)
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return None

    initial_median = statistics.median(gaps)
    threshold = 3.0 * initial_median
    filtered = [g for g in gaps if g <= threshold]

    if not filtered:
        # All gaps were hiatuses — fall back to the full set
        filtered = gaps

    result = statistics.median(filtered)
    return result if result >= 1.0 else None
