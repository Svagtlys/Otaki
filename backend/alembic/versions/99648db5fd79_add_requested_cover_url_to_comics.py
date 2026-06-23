"""add requested_cover_url to comics

Revision ID: 99648db5fd79
Revises: 5ffa82538c2f
Create Date: 2026-03-31 09:24:19.684920

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "99648db5fd79"
down_revision: str | Sequence[str] | None = "5ffa82538c2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("comics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("requested_cover_url", sa.String(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("comics", schema=None) as batch_op:
        batch_op.drop_column("requested_cover_url")
