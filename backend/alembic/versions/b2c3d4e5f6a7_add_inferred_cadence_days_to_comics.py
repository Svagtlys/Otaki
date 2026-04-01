"""add inferred_cadence_days to comics

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("comics") as batch_op:
        batch_op.add_column(sa.Column("inferred_cadence_days", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("comics") as batch_op:
        batch_op.drop_column("inferred_cadence_days")
