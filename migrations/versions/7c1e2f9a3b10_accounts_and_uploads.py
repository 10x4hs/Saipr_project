"""accounts and private uploads

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
    op.add_column('users', sa.Column('password_hash', sa.String(length=60), nullable=True))
    op.add_column('books', sa.Column('owner_id', sa.Integer(), nullable=True))
    op.add_column('books', sa.Column('fingerprint', sa.String(length=64), nullable=True))
    op.create_foreign_key(op.f('fk_books_owner_id_users'), 'books', 'users', ['owner_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_books_owner_id'), 'books', ['owner_id'], unique=False)
    op.create_index(op.f('ix_books_fingerprint'), 'books', ['fingerprint'], unique=False)
    op.add_column('library_entries', sa.Column('current_chunk', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('library_entries', 'current_chunk')
    op.drop_index(op.f('ix_books_fingerprint'), table_name='books')
    op.drop_index(op.f('ix_books_owner_id'), table_name='books')
    op.drop_constraint(op.f('fk_books_owner_id_users'), 'books', type_='foreignkey')
    op.drop_column('books', 'fingerprint')
    op.drop_column('books', 'owner_id')
    op.drop_column('users', 'password_hash')
