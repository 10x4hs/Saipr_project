"""내 서재 (PRD LIB-01) · 트래커 모드 (PRD READ-02)."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, LibraryEntry, Shelf
from app.sources.base import BookMeta

# 메타데이터만 주는 상용 도서 소스. 퍼블릭 도메인 소스(wikisource·gutendex)는 /books/import로 전문을 가져온다.
TRACKER_SOURCES = frozenset({"kakao", "naver", "google_books", "manual"})


class LibraryError(Exception):
    pass


async def get_entry(session: AsyncSession, user_id: int, book_id: int) -> LibraryEntry | None:
    return await session.scalar(
        select(LibraryEntry).where(LibraryEntry.user_id == user_id, LibraryEntry.book_id == book_id)
    )


async def ensure_entry(
    session: AsyncSession, user_id: int, book_id: int, shelf: Shelf = Shelf.READING
) -> LibraryEntry:
    if entry := await get_entry(session, user_id, book_id):
        return entry
    entry = LibraryEntry(user_id=user_id, book_id=book_id, shelf=shelf, progress_pct=0, verified_chunk=-1)
    session.add(entry)
    await session.flush()
    return entry


async def list_entries(session: AsyncSession, user_id: int) -> list[tuple[LibraryEntry, Book]]:
    rows = await session.execute(
        select(LibraryEntry, Book)
        .join(Book, Book.id == LibraryEntry.book_id)
        .where(LibraryEntry.user_id == user_id)
        .order_by(LibraryEntry.updated_at.desc(), LibraryEntry.id.desc())
    )
    return [(e, b) for e, b in rows.all()]


async def set_shelf(session: AsyncSession, user_id: int, book_id: int, shelf: Shelf) -> LibraryEntry:
    entry = await ensure_entry(session, user_id, book_id, shelf)
    if shelf is Shelf.DONE:
        # 완독 포인트는 complete_book에서만 준다. 순환 import를 피하려고 여기서 불러온다.
        from app.services.points import complete_book

        book = await session.get(Book, book_id)
        await complete_book(session, entry, book)
    else:
        entry.shelf = shelf
    try:
        await session.commit()
    except IntegrityError:
        # 완독 버튼을 동시에 두 번 눌러 같은 포인트가 두 번 들어가려 한 경우 — DB UNIQUE가 막았다
        await session.rollback()
        entry = await get_entry(session, user_id, book_id) or entry
    return entry


def pct_from_pages(current_page: int, total_pages: int) -> int:
    if total_pages <= 0:
        raise LibraryError("전체 쪽수는 1 이상이어야 해요.")
    return max(0, min(100, current_page * 100 // total_pages))


async def set_tracker_progress(session: AsyncSession, user_id: int, book: Book, pct: int) -> LibraryEntry:
    """본문이 없는 책만 수동 진행률을 받는다. 인앱 리더 책은 체류시간 검증으로만 오른다."""
    if book.has_fulltext:
        raise LibraryError("앱 안에서 읽는 책은 진행률을 직접 입력할 수 없어요.")
    entry = await ensure_entry(session, user_id, book.id)
    entry.progress_pct = max(0, min(100, pct))
    if entry.shelf is Shelf.WANT and entry.progress_pct > 0:
        entry.shelf = Shelf.READING
    await session.commit()
    return entry


async def register_tracker_book(session: AsyncSession, meta: BookMeta) -> Book:
    """검색 결과의 상용 도서를 메타데이터만으로 등록. 본문은 절대 저장하지 않는다."""
    if meta.source not in TRACKER_SOURCES:
        # 같은 (source, external_id)로 빈 책이 먼저 생기면 나중에 전문을 가져올 수 없다
        raise LibraryError(f"트래커로 등록할 수 있는 소스: {', '.join(sorted(TRACKER_SOURCES))}")
    existing = await session.scalar(
        select(Book).where(Book.source == meta.source, Book.external_id == meta.external_id)
    )
    if existing:
        return existing
    book = Book(
        source=meta.source,
        external_id=meta.external_id[:512],
        isbn13=meta.isbn13,
        title=meta.title[:500],
        author=", ".join(meta.authors)[:300] or None,
        cover_url=meta.cover_url,
        language=meta.language,
        has_fulltext=False,
        total_chunks=0,
    )
    session.add(book)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(Book).where(Book.source == meta.source, Book.external_id == meta.external_id)
        )
        if existing is None:
            raise
        return existing
    return book


def position_of(entry: LibraryEntry | None, book: Book) -> int:
    """스포일러 가드·반응 위치 비교용 좌표. 전문 도서=검증된 최대 청크, 트래커=10% 구간(0~9)."""
    if entry is None:
        return -1
    if book.has_fulltext:
        return entry.verified_chunk
    return min(9, entry.progress_pct // 10) if entry.progress_pct > 0 else -1
