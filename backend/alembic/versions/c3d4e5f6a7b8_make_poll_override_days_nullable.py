"""make poll_override_days nullable

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("comics") as batch_op:
        batch_op.alter_column(
            "poll_override_days",
            existing_type=sa.Float(),
            nullable=True,
        )


def downgrade() -> None:
    # Restore non-null: fill any nulls with the historical default (7.0) first.
    op.execute("UPDATE comics SET poll_override_days = 7.0 WHERE poll_override_days IS NULL")
    with op.batch_alter_table("comics") as batch_op:
        batch_op.alter_column(
            "poll_override_days",
            existing_type=sa.Float(),
            nullable=False,
        )
