"""worker A: signup email verification codes

Revision ID: a1f0c3d5e7b9
Revises: e2f7a3c9b815
Create Date: 2026-11-06 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a1f0c3d5e7b9'
down_revision: str | None = 'e2f7a3c9b815'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'signup_verifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('nickname', sa.String(length=40), nullable=False),
        sa.Column('password_hash', sa.String(length=60), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('expires_at', sa.BigInteger(), nullable=False),
        sa.Column('sent_at', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )


def downgrade() -> None:
    op.drop_table('signup_verifications')
