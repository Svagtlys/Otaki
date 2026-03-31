"""add comic_aliases table

Revision ID: a1b2c3d4e5f6
Revises: 99648db5fd79
Create Date: 2026-03-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "99648db5fd79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comic_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comic_id", sa.Integer(), sa.ForeignKey("comics.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comic_aliases_comic_id", "comic_aliases", ["comic_id"])


def downgrade() -> None:
    op.drop_index("ix_comic_aliases_comic_id", table_name="comic_aliases")
    op.drop_table("comic_aliases")
