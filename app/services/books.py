from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, BookChunk
from app.services.chunker import chunk_text, target_for
from app.services.search import FULLTEXT_SOURCES
from app.sources.base import BookSource, SourceError


async def _find(session: AsyncSession, source: str, external_id: str) -> Book | None:
    return await session.scalar(select(Book).where(Book.source == source, Book.external_id == external_id))


async def import_book(session: AsyncSession, source: BookSource, external_id: str) -> Book:
    """퍼블릭 도메인 전문을 가져와 청크로 저장. 이미 있으면 외부 호출 없이 캐시를 반환."""
    if source.name not in FULLTEXT_SOURCES:
        raise SourceError(f"{source.name} is not a public-domain full-text source")
    if book := await _find(session, source.name, external_id):
        return book

    meta, text = await source.fetch_book(external_id)
    chunks = chunk_text(text, target_for(meta.language))
    if not chunks:
        raise SourceError("empty text")

    book = Book(
        source=source.name,
        external_id=external_id,
        isbn13=meta.isbn13,
        title=meta.title[:500],
        author=", ".join(meta.authors)[:300] or None,
        cover_url=meta.cover_url,
        language=meta.language,
        has_fulltext=True,
        total_chunks=len(chunks),
        chunks=[BookChunk(chunk_index=i, text=c, char_count=len(c)) for i, c in enumerate(chunks)],
    )
    session.add(book)
    try:
        await session.commit()
    except IntegrityError:
        # 동시에 같은 책을 가져온 요청이 먼저 커밋한 경우
        await session.rollback()
        if existing := await _find(session, source.name, external_id):
            return existing
        raise
    return book


async def get_chunk(session: AsyncSession, book_id: int, chunk_index: int) -> tuple[Book, BookChunk] | None:
    row = (
        await session.execute(
            select(Book, BookChunk)
            .join(BookChunk, BookChunk.book_id == Book.id)
            .where(Book.id == book_id, BookChunk.chunk_index == chunk_index)
        )
    ).first()
    return (row[0], row[1]) if row else None
