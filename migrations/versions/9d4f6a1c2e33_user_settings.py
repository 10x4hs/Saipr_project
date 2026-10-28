"""user display settings

Revision ID: 9d4f6a1c2e33
Revises: 7c1e2f9a3b10
Create Date: 2026-10-29 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '9d4f6a1c2e33'
down_revision: str | None = '7c1e2f9a3b10'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('settings', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'settings')
