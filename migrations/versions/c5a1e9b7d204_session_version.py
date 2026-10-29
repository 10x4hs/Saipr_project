"""session version for server-side logout

Revision ID: c5a1e9b7d204
Revises: b3e8d2f4a611
Create Date: 2026-10-29 13:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c5a1e9b7d204'
down_revision: str | None = 'b3e8d2f4a611'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('session_version', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'session_version')
