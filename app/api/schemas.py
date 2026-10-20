"""네이티브 앱 API가 함께 쓰는 응답 모양 (docs/plans/2026-10-20-native-app-design.md 'API 계약')."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models import Book, Highlight, User
from app.services.catalog import cover_color


class UserMini(BaseModel):
    id: int
    nickname: str
    avatar_color: str


class UserSearchOut(UserMini):
    is_following: bool


class MeOut(BaseModel):
    id: int
    nickname: str
    email: str | None
    spoiler_guard: bool
    friend_code: str
    bio: str | None
    avatar_color: str
    daily_goal_minutes: int
    yearly_goal_books: int


class BookCard(BaseModel):
    id: int
    title: str
    author: str | None
    genre: str | None
    has_fulltext: bool
    total_chunks: int
    cover_url: str | None
    cover_color: str
    readers: int


class HighlightOut(BaseModel):
    id: int
    book_id: int
    chunk_index: int
    anchor: int
    quote: str
    note: str | None
    color: str
    visibility: str
    created_at: datetime
    user: UserMini


class MyHighlightOut(HighlightOut):
    book: BookCard


class ActivityOut(BaseModel):
    id: int
    user: UserMini
    kind: str
    book: BookCard | None
    data: dict[str, Any]
    created_at: datetime


def user_mini(u: User) -> UserMini:
    return UserMini(id=u.id, nickname=u.nickname, avatar_color=u.color)


def me_out(u: User) -> MeOut:
    return MeOut(
        id=u.id,
        nickname=u.nickname,
        email=u.email,
        spoiler_guard=u.spoiler_guard,
        friend_code=u.friend_code,
        bio=u.bio,
        avatar_color=u.color,
        daily_goal_minutes=u.daily_goal_minutes,
        yearly_goal_books=u.yearly_goal_books,
    )


def book_card(b: Book, readers: int) -> BookCard:
    return BookCard(
        id=b.id,
        title=b.title,
        author=b.author,
        genre=b.genre,
        has_fulltext=b.has_fulltext,
        total_chunks=b.total_chunks,
        cover_url=b.cover_url,
        cover_color=cover_color(b.id),
        readers=readers,
    )


def highlight_out(h: Highlight, author: User) -> HighlightOut:
    return HighlightOut(
        id=h.id,
        book_id=h.book_id,
        chunk_index=h.chunk_index,
        anchor=h.anchor,
        quote=h.quote,
        note=h.comment,
        color=h.color,
        visibility=h.visibility,
        created_at=h.created_at,
        user=user_mini(author),
    )
