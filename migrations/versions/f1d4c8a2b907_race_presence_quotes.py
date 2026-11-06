"""worker D: race presence and quote feed

Revision ID: f1d4c8a2b907
Revises: a1f0c3d5e7b9
Create Date: 2026-11-06 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f1d4c8a2b907'
down_revision: str | None = 'a1f0c3d5e7b9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'race_presence',
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], name=op.f('fk_race_presence_room_id_rooms'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_race_presence_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('room_id', 'user_id', name=op.f('pk_race_presence')),
    )
    op.create_table(
        'race_quotes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('body', sa.String(length=280), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], name=op.f('fk_race_quotes_room_id_rooms'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_race_quotes_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_race_quotes')),
    )
    op.create_index('ix_race_quotes_room_id_id', 'race_quotes', ['room_id', 'id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_race_quotes_room_id_id', table_name='race_quotes')
    op.drop_table('race_quotes')
    op.drop_table('race_presence')
