import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Book, BookChunk, LibraryEntry, ReadingEvent, Shelf
from app.services.chunker import chunk_text, target_for
from app.services.pace import credited_dwell_ms, is_verified, min_dwell_ms
from app.services.search import FULLTEXT_SOURCES
from app.services.uploads import ParsedBook, fingerprint
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


UPLOAD_SOURCE = "upload"


def required_dwell_ms(text: str, language: str | None) -> int:
    return int(min_dwell_ms(text, language) * get_settings().dwell_scale)


def clock() -> dt.datetime:
    """현재 시각 — 테스트에서 시간을 흘려보낼 수 있게 한곳에 둔다."""
    return dt.datetime.now(dt.UTC)


def can_read(book: Book, user_id: int | None) -> bool:
    """퍼블릭 도메인 책은 로그인한 누구나, 올린 책은 올린 사람만 읽는다."""
    if not book.has_fulltext or user_id is None:
        return False
    return book.owner_id is None or book.owner_id == user_id


async def save_upload(session: AsyncSession, parsed: ParsedBook, user_id: int) -> Book:
    """같은 사람이 같은 책을 다시 올리면 새로 만들지 않고 기존 책을 돌려준다."""
    fp = fingerprint(parsed.text)
    if existing := await session.scalar(
        select(Book).where(Book.source == UPLOAD_SOURCE, Book.owner_id == user_id, Book.fingerprint == fp)
    ):
        return existing
    chunks = chunk_text(parsed.text, target_for(parsed.language))
    book = Book(
        source=UPLOAD_SOURCE,
        external_id=uuid.uuid4().hex,
        title=parsed.title,
        author=parsed.author,
        language=parsed.language,
        has_fulltext=True,
        total_chunks=len(chunks),
        owner_id=user_id,
        fingerprint=fp,
        chunks=[BookChunk(chunk_index=i, text=c, char_count=len(c)) for i, c in enumerate(chunks)],
    )
    session.add(book)
    await session.commit()
    return book


# --- 내 서재 ---


async def shelve(session: AsyncSession, user_id: int, book_id: int) -> LibraryEntry:
    """책을 펼치면 서재에 '읽는 중'으로 꽂는다 (이미 있으면 그대로)."""
    entry = await session.scalar(
        select(LibraryEntry).where(LibraryEntry.user_id == user_id, LibraryEntry.book_id == book_id)
    )
    if entry is None:
        entry = LibraryEntry(user_id=user_id, book_id=book_id, shelf=Shelf.READING)
        session.add(entry)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return await shelve(session, user_id, book_id)
    return entry


async def record_progress(
    session: AsyncSession, user_id: int, book: Book, chunk_index: int, verified: bool
) -> LibraryEntry:
    """위치를 저장하고, '다 읽었다'는 요청은 서버가 잰 체류시간으로 판정한다.

    쪽을 펼칠 때(verified=False) 시각을 남기고, 다 읽었다는 요청이 오면 그 사이 시간이
    청크 글자 수로 정한 최소 체류시간을 넘었을 때만 인정한다(PRD BTL-01, GOAL #6).
    클라이언트가 보낸 verified 값만 믿으면 API 한 번으로 레이스 점수를 올릴 수 있다.
    """
    entry = await shelve(session, user_id, book.id)
    chunk_index = max(0, min(chunk_index, book.total_chunks - 1))
    now = clock()
    entry.current_chunk = chunk_index
    if not verified:
        session.add(
            ReadingEvent(
                user_id=user_id,
                book_id=book.id,
                chunk_index=chunk_index,
                dwell_ms=0,
                verified=False,
                occurred_at=now,
            )
        )
    elif chunk_index == entry.verified_chunk + 1:  # 순서대로 읽은 쪽만
        mine = (ReadingEvent.user_id == user_id, ReadingEvent.book_id == book.id)
        # 앞 쪽을 다 읽은 뒤에 펼친 기록만 센다 — 여러 쪽을 미리 펼쳐 두고 한꺼번에 인정받는 것을 막는다
        since = await session.scalar(
            select(func.max(ReadingEvent.occurred_at)).where(
                *mine, ReadingEvent.chunk_index == chunk_index - 1, ReadingEvent.verified.is_(True)
            )
        )
        # 그중 가장 이른 펼침부터 잰다(다시 보내도 처음부터 다시 세지 않는다).
        # 실패한 판정 기록(dwell_ms > 0)은 펼침이 아니다
        q = select(func.min(ReadingEvent.occurred_at)).where(
            *mine,
            ReadingEvent.chunk_index == chunk_index,
            ReadingEvent.verified.is_(False),
            ReadingEvent.dwell_ms == 0,
        )
        if since is not None:
            q = q.where(ReadingEvent.occurred_at >= since)
        opened = await session.scalar(q)
        if opened is not None:
            if opened.tzinfo is None:  # SQLite는 시간대를 버린다
                opened = opened.replace(tzinfo=dt.UTC)
            chunk = await session.scalar(
                select(BookChunk).where(BookChunk.book_id == book.id, BookChunk.chunk_index == chunk_index)
            )
            need = required_dwell_ms(chunk.text, book.language) if chunk else 0
            dwell = credited_dwell_ms(int((now - opened).total_seconds() * 1000), need)
            ok = is_verified(dwell, need)
            session.add(
                ReadingEvent(
                    user_id=user_id,
                    book_id=book.id,
                    chunk_index=chunk_index,
                    dwell_ms=max(dwell, 1),  # 0이면 '펼침'과 구별되지 않는다
                    verified=ok,
                    occurred_at=now,
                )
            )
            if ok:
                entry.verified_chunk = chunk_index
    entry.progress_pct = round((entry.verified_chunk + 1) / max(book.total_chunks, 1) * 100)
    if entry.verified_chunk >= book.total_chunks - 1:
        entry.shelf = Shelf.DONE
    await session.commit()
    return entry


async def library_of(session: AsyncSession, user_id: int) -> list[tuple[LibraryEntry, Book]]:
    rows = await session.execute(
        select(LibraryEntry, Book)
        .join(Book, Book.id == LibraryEntry.book_id)
        .where(LibraryEntry.user_id == user_id)
        .order_by(LibraryEntry.updated_at.desc(), LibraryEntry.id.desc())
    )
    return [(e, b) for e, b in rows.all()]


async def uploads_of(session: AsyncSession, user_id: int) -> list[Book]:
    rows = await session.scalars(select(Book).where(Book.owner_id == user_id).order_by(Book.id.desc()))
    return list(rows)
