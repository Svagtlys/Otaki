"""initial schema

Revision ID: 9b822e5ef4dc
Revises:
Create Date: 2026-03-29 22:15:33.773416

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b822e5ef4dc'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username'),
    )
    op.create_table(
        'comics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('library_title', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('poll_override_days', sa.Float(), nullable=False),
        sa.Column('upgrade_override_days', sa.Float(), nullable=True),
        sa.Column('cover_path', sa.String(), nullable=True),
        sa.Column('next_poll_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_upgrade_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_upgrade_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('suwayomi_source_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('suwayomi_source_id'),
    )
    op.create_table(
        'chapter_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('comic_id', sa.Integer(), sa.ForeignKey('comics.id'), nullable=False),
        sa.Column('chapter_number', sa.Float(), nullable=False),
        sa.Column('volume_number', sa.Integer(), nullable=True),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('sources.id'), nullable=False),
        sa.Column('suwayomi_manga_id', sa.String(), nullable=False),
        sa.Column('suwayomi_chapter_id', sa.String(), nullable=False),
        sa.Column('download_status', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('chapter_published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('downloaded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('library_path', sa.String(), nullable=True),
        sa.Column('relocation_status', sa.String(), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_chapter_assignments_comic_chapter_active',
        'chapter_assignments',
        ['comic_id', 'chapter_number', 'is_active'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chapter_assignments_comic_chapter_active', table_name='chapter_assignments')
    op.drop_table('chapter_assignments')
    op.drop_table('sources')
    op.drop_table('comics')
    op.drop_table('users')
