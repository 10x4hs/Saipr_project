"""앱의 책 목록 · 책 카드에 필요한 값 (표지 색, 읽는 사람 수, 원문 링크)."""

import zlib
from collections.abc import Iterable
from typing import Literal
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, BookChunk, LibraryEntry

GENRES = ("소설", "시", "수필")
Sort = Literal["popular", "new"]
# 웹 화면(app/web/view.py COVER_COLORS)과 같은 팔레트 · 같은 계산이라 웹과 앱의 표지 색이 같다
COVER_COLORS = ("#8e6c4a", "#b5523b", "#3a5a8c", "#2f6b4f", "#6b4f8e", "#8c3a5a", "#4a7a8c", "#7a6a3a")


def cover_color(book_id: int) -> str:
    return COVER_COLORS[zlib.crc32(str(book_id).encode()) % len(COVER_COLORS)]


def source_url(book: Book) -> str | None:
    """원문(퍼블릭 도메인) 또는 서지 정보가 있는 곳."""
    if book.source == "wikisource":
        return f"https://ko.wikisource.org/wiki/{quote(book.external_id.replace(' ', '_'))}"
    if book.source == "gutendex":
        return f"https://www.gutenberg.org/ebooks/{quote(book.external_id)}"
    return None


async def readers_counts(session: AsyncSession, book_ids: Iterable[int]) -> dict[int, int]:
    """책마다 서재에 담은 사람 수."""
    ids = set(book_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(LibraryEntry.book_id, func.count())
        .where(LibraryEntry.book_id.in_(ids))
        .group_by(LibraryEntry.book_id)
    )
    counts = {i: 0 for i in ids}
    counts.update({b: int(n) for b, n in rows.all()})
    return counts


async def list_books(
    session: AsyncSession, genre: str | None = None, sort: Sort = "popular", limit: int = 30
) -> list[tuple[Book, int]]:
    readers = select(LibraryEntry.book_id, func.count().label("n")).group_by(LibraryEntry.book_id).subquery()
    n = func.coalesce(readers.c.n, 0)
    q = select(Book, n).outerjoin(readers, readers.c.book_id == Book.id)
    if genre is not None:
        q = q.where(Book.genre == genre)
    q = q.order_by(n.desc(), Book.id.desc()) if sort == "popular" else q.order_by(Book.id.desc())
    rows = await session.execute(q.limit(limit))
    return [(b, int(c)) for b, c in rows.all()]


async def total_chars(session: AsyncSession, book_id: int) -> int:
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(BookChunk.char_count), 0)).where(BookChunk.book_id == book_id)
        )
    )
