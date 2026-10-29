"""indexes for race membership, rooms by book and readers per book

Revision ID: e2f7a3c9b815
Revises: c5a1e9b7d204
Create Date: 2026-10-30 10:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = 'e2f7a3c9b815'
down_revision: str | None = 'c5a1e9b7d204'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(op.f('ix_room_members_user_id'), 'room_members', ['user_id'], unique=False)
    op.create_index(op.f('ix_rooms_book_id'), 'rooms', ['book_id'], unique=False)
    op.create_index(op.f('ix_library_entries_book_id'), 'library_entries', ['book_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_library_entries_book_id'), table_name='library_entries')
    op.drop_index(op.f('ix_rooms_book_id'), table_name='rooms')
    op.drop_index(op.f('ix_room_members_user_id'), table_name='room_members')
