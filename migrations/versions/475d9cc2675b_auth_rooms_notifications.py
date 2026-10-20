"""auth rooms notifications — 이메일 로그인 · 스포일러 가드 설정 · 초대 만료 · 방 보관 · 팀 초대 · 알림함

Revision ID: 475d9cc2675b
Revises: 4b551282b547
Create Date: 2026-10-20 12:07:10.427425
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '475d9cc2675b'
down_revision: str | None = '4b551282b547'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 기본값은 DB 공통 표현(sa.true()/sa.func.now())으로 맞췄다. SQLite 렌더링을 그대로 두면 Postgres에서 실패한다.
    op.create_table('notifications',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('body', sa.String(length=280), nullable=False),
    sa.Column('link', sa.String(length=300), nullable=True),
    sa.Column('deliver_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index('ix_notifications_user_created', 'notifications', ['user_id', 'created_at'], unique=False)
    op.add_column('reading_events', sa.Column('race_eligible', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column('rooms', sa.Column('invite_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('rooms', sa.Column('archived', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('teams', sa.Column('invite_code', sa.String(length=16), nullable=True))
    op.create_unique_constraint(op.f('uq_teams_invite_code'), 'teams', ['invite_code'])
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('spoiler_guard', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column('reading_events', sa.Column('received_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('team_members', sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    # 기존 데이터에 중복이 있으면 실패한다 — Phase 1까지는 이 테이블을 쓰는 코드가 없어 비어 있다
    op.create_index('uq_reading_events_verified_once', 'reading_events', ['user_id', 'book_id', 'chunk_index'],
                    unique=True, postgresql_where=sa.text('verified'), sqlite_where=sa.text('verified'))
    op.create_index('uq_points_log_ref', 'points_log', ['user_id', 'source', 'ref_id'], unique=True,
                    postgresql_where=sa.text('ref_id IS NOT NULL'), sqlite_where=sa.text('ref_id IS NOT NULL'))


def downgrade() -> None:
    op.drop_index('uq_points_log_ref', table_name='points_log')
    op.drop_index('uq_reading_events_verified_once', table_name='reading_events')
    op.drop_column('team_members', 'joined_at')
    op.drop_column('reading_events', 'received_at')
    # 기본값은 DB 공통 표현(sa.true()/sa.func.now())으로 맞췄다. SQLite 렌더링을 그대로 두면 Postgres에서 실패한다.
    op.drop_column('users', 'spoiler_guard')
    op.drop_column('users', 'password_hash')
    op.drop_constraint(op.f('uq_teams_invite_code'), 'teams', type_='unique')
    op.drop_column('teams', 'invite_code')
    op.drop_column('rooms', 'archived')
    op.drop_column('rooms', 'invite_expires_at')
    op.drop_column('reading_events', 'race_eligible')
    op.drop_index('ix_notifications_user_created', table_name='notifications')
    op.drop_table('notifications')
