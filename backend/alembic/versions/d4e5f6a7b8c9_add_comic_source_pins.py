"""add comic_source_pins table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comic_source_pins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comic_id", sa.Integer(), sa.ForeignKey("comics.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("suwayomi_manga_id", sa.String(), nullable=False),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comic_id", "source_id", "suwayomi_manga_id", name="uq_comic_source_pins"),
    )
    op.create_index("ix_comic_source_pins_comic_id", "comic_source_pins", ["comic_id"])


def downgrade() -> None:
    op.drop_index("ix_comic_source_pins_comic_id", table_name="comic_source_pins")
    op.drop_table("comic_source_pins")
