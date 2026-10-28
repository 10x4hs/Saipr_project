"""private uploads: owner key and fingerprint on books

Revision ID: 7c1e2f9a3b10
Revises: 4b551282b547
Create Date: 2026-10-29 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '7c1e2f9a3b10'
down_revision: str | None = '4b551282b547'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('books', sa.Column('owner_key_hash', sa.String(length=64), nullable=True))
    op.add_column('books', sa.Column('fingerprint', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_books_fingerprint'), 'books', ['fingerprint'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_books_fingerprint'), table_name='books')
    op.drop_column('books', 'fingerprint')
    op.drop_column('books', 'owner_key_hash')
