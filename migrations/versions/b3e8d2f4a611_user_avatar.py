"""user avatar

Revision ID: b3e8d2f4a611
Revises: 9d4f6a1c2e33
Create Date: 2026-10-29 12:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b3e8d2f4a611'
down_revision: str | None = '9d4f6a1c2e33'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('avatar', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'avatar')
