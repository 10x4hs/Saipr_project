"""native app — Bearer 토큰 · 프로필(친구 코드·목표) · 팔로우 · 응원 · 활동 피드 · 방 채팅 · 개인 밑줄 · 책 소개 캐시

Revision ID: d8b28b0a5b33
Revises: 49c521870d1f
Create Date: 2026-10-20 19:22:21.674685
"""
import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'd8b28b0a5b33'
down_revision: str | None = '49c521870d1f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# app/models.py와 같은 규칙(헷갈리는 0·O·1·I를 뺀 32자 × 6자리). 모델을 import하지 않아야 나중에 모델이 바뀌어도 이 파일이 그대로 돈다
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _codes(n: int) -> list[str]:
    seen: set[str] = set()
    while len(seen) < n:
        seen.add("".join(secrets.choice(_ALPHABET) for _ in range(6)))
    return list(seen)


def upgrade() -> None:
    # 기본값은 DB 공통 표현(sa.func.now() 등)으로 맞췄다. 조건부 UNIQUE는 기존 마이그레이션처럼 두 DB 모두에 적는다.
    op.create_table('activities',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('book_id', sa.Integer(), nullable=True),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('ref', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['book_id'], ['books.id'], name=op.f('fk_activities_book_id_books'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_activities_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_activities'))
    )
    op.create_index('ix_activities_user_id_id', 'activities', ['user_id', 'id'], unique=False)
    op.create_index('uq_activities_user_ref', 'activities', ['user_id', 'ref'], unique=True,
                    postgresql_where=sa.text('ref IS NOT NULL'), sqlite_where=sa.text('ref IS NOT NULL'))
    op.create_table('api_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_api_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_api_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_api_tokens_token_hash'))
    )
    op.create_index(op.f('ix_api_tokens_user_id'), 'api_tokens', ['user_id'], unique=False)
    op.create_table('cheers',
    sa.Column('sender_id', sa.Integer(), nullable=False),
    sa.Column('receiver_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['receiver_id'], ['users.id'], name=op.f('fk_cheers_receiver_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], name=op.f('fk_cheers_sender_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('sender_id', 'receiver_id', 'day', name=op.f('pk_cheers'))
    )
    op.create_table('follows',
    sa.Column('follower_id', sa.Integer(), nullable=False),
    sa.Column('followee_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.CheckConstraint('follower_id <> followee_id', name=op.f('ck_follows_not_self')),
    sa.ForeignKeyConstraint(['followee_id'], ['users.id'], name=op.f('fk_follows_followee_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['follower_id'], ['users.id'], name=op.f('fk_follows_follower_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('follower_id', 'followee_id', name=op.f('pk_follows'))
    )
    op.create_index('ix_follows_followee', 'follows', ['followee_id'], unique=False)
    op.create_table('room_messages',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('room_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.String(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], name=op.f('fk_room_messages_room_id_rooms'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_room_messages_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_room_messages'))
    )
    op.create_index('ix_room_messages_room_id_id', 'room_messages', ['room_id', 'id'], unique=False)
    op.add_column('books', sa.Column('genre', sa.String(length=10), nullable=True))
    op.add_column('books', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('books', sa.Column('author_bio', sa.Text(), nullable=True))
    op.add_column('books', sa.Column('wiki_url', sa.String(length=1000), nullable=True))
    op.add_column('books', sa.Column('info_fetched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('highlights', sa.Column('color', sa.String(length=10), server_default='yellow', nullable=False))
    op.add_column('highlights', sa.Column('visibility', sa.String(length=10), server_default='private', nullable=False))
    op.create_index('ix_highlights_book_chunk', 'highlights', ['book_id', 'chunk_index'], unique=False)
    op.create_index('ix_highlights_user_book', 'highlights', ['user_id', 'book_id'], unique=False)
    op.add_column('users', sa.Column('bio', sa.String(length=160), nullable=True))
    op.add_column('users', sa.Column('avatar_color', sa.String(length=9), nullable=True))
    op.add_column('users', sa.Column('daily_goal_minutes', sa.SmallInteger(), server_default=sa.text('20'), nullable=False))
    op.add_column('users', sa.Column('yearly_goal_books', sa.SmallInteger(), server_default=sa.text('12'), nullable=False))

    # 친구 코드: 기존 사용자에게 겹치지 않는 코드를 채운 뒤 NOT NULL · UNIQUE로 바꾼다
    op.add_column('users', sa.Column('friend_code', sa.String(length=6), nullable=True))
    conn = op.get_bind()
    users = sa.table('users', sa.column('id', sa.Integer()), sa.column('friend_code', sa.String()))
    ids = [row[0] for row in conn.execute(sa.select(users.c.id))]
    for uid, code in zip(ids, _codes(len(ids)), strict=True):
        conn.execute(sa.update(users).where(users.c.id == uid).values(friend_code=code))
    with op.batch_alter_table('users') as batch:
        batch.alter_column('friend_code', existing_type=sa.String(length=6), nullable=False)
        batch.create_unique_constraint(op.f('uq_users_friend_code'), ['friend_code'])


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint(op.f('uq_users_friend_code'), type_='unique')
        batch.drop_column('friend_code')
    op.drop_column('users', 'yearly_goal_books')
    op.drop_column('users', 'daily_goal_minutes')
    op.drop_column('users', 'avatar_color')
    op.drop_column('users', 'bio')
    op.drop_index('ix_highlights_user_book', table_name='highlights')
    op.drop_index('ix_highlights_book_chunk', table_name='highlights')
    op.drop_column('highlights', 'visibility')
    op.drop_column('highlights', 'color')
    op.drop_column('books', 'info_fetched_at')
    op.drop_column('books', 'wiki_url')
    op.drop_column('books', 'author_bio')
    op.drop_column('books', 'description')
    op.drop_column('books', 'genre')
    op.drop_index('ix_room_messages_room_id_id', table_name='room_messages')
    op.drop_table('room_messages')
    op.drop_index('ix_follows_followee', table_name='follows')
    op.drop_table('follows')
    op.drop_table('cheers')
    op.drop_index(op.f('ix_api_tokens_user_id'), table_name='api_tokens')
    op.drop_table('api_tokens')
    op.drop_index('uq_activities_user_ref', table_name='activities')
    op.drop_index('ix_activities_user_id_id', table_name='activities')
    op.drop_table('activities')
