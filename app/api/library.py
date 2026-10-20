from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_book, verify_csrf
from app.db.session import get_session
from app.models import Book, LibraryEntry, Shelf, User
from app.services import library as lib
from app.services import reading
from app.sources.base import BookMeta

router = APIRouter(prefix="/api/v1", tags=["library"], dependencies=[Depends(verify_csrf)])


class EntryOut(BaseModel):
    book_id: int
    title: str
    author: str | None
    cover_url: str | None
    has_fulltext: bool
    total_chunks: int
    shelf: Shelf
    progress_pct: int
    verified_chunk: int


def entry_out(e: LibraryEntry, b: Book) -> EntryOut:
    return EntryOut(
        book_id=b.id,
        title=b.title,
        author=b.author,
        cover_url=b.cover_url,
        has_fulltext=b.has_fulltext,
        total_chunks=b.total_chunks,
        shelf=e.shelf,
        progress_pct=e.progress_pct,
        verified_chunk=e.verified_chunk,
    )


class ShelfIn(BaseModel):
    shelf: Shelf


class ProgressIn(BaseModel):
    """% 또는 (현재 쪽, 전체 쪽) 중 하나. 쪽수는 %로 바꿔 저장한다."""

    progress_pct: int | None = Field(None, ge=0, le=100)
    current_page: int | None = Field(None, ge=0)
    total_pages: int | None = Field(None, ge=1)


class TrackIn(BaseModel):
    source: str
    external_id: str
    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = []
    isbn13: str | None = None
    cover_url: str | None = None
    language: str | None = None


class EventIn(BaseModel):
    chunk_index: int
    dwell_ms: int = Field(ge=0, le=3_600_000)
    occurred_at: datetime


class EventsIn(BaseModel):
    events: list[EventIn] = Field(max_length=reading.MAX_BATCH)


class EventsOut(BaseModel):
    accepted: int
    newly_verified: list[int]
    verified_chunk: int
    progress_pct: int
    points_awarded: int
    slow_down: bool
    suggest_done: bool


@router.get("/library", response_model=list[EntryOut])
async def my_library(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [entry_out(e, b) for e, b in await lib.list_entries(session, user.id)]


@router.put("/library/{book_id}", response_model=EntryOut)
async def set_shelf(
    body: ShelfIn,
    book: Book = Depends(get_book),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    entry = await lib.set_shelf(session, user.id, book.id, body.shelf)
    return entry_out(entry, book)


@router.put("/library/{book_id}/progress", response_model=EntryOut)
async def set_progress(
    body: ProgressIn,
    book: Book = Depends(get_book),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if body.progress_pct is not None:
        pct = body.progress_pct
    elif body.current_page is not None and body.total_pages:
        pct = lib.pct_from_pages(body.current_page, body.total_pages)
    else:
        raise HTTPException(422, "progress_pct 또는 current_page·total_pages가 필요해요.")
    entry = await lib.set_tracker_progress(session, user.id, book, pct)
    return entry_out(entry, book)


@router.post("/books/track", response_model=EntryOut)
async def track_book(
    body: TrackIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    """상용 도서를 트래커 모드로 서재에 추가 (메타데이터만, has_fulltext는 항상 false)."""
    meta = BookMeta(
        source=body.source,
        external_id=body.external_id,
        title=body.title,
        authors=tuple(body.authors),
        isbn13=body.isbn13,
        cover_url=body.cover_url,
        language=body.language,
        has_fulltext=False,
    )
    book = await lib.register_tracker_book(session, meta)
    entry = await lib.ensure_entry(session, user.id, book.id, Shelf.WANT)
    await session.commit()
    return entry_out(entry, book)


@router.post("/books/{book_id}/events", response_model=EventsOut)
async def post_events(
    body: EventsIn,
    book: Book = Depends(get_book),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    r = await reading.record_events(
        session, user, book, [reading.EventIn(e.chunk_index, e.dwell_ms, e.occurred_at) for e in body.events]
    )
    entry = await lib.get_entry(session, user.id, book.id)
    return EventsOut(
        accepted=r.accepted,
        newly_verified=r.newly_verified,
        verified_chunk=r.verified_chunk,
        progress_pct=r.progress_pct,
        points_awarded=r.points_awarded,
        slow_down=r.slow_down,
        # 100%가 되면 완독 전환을 '제안'만 한다 (자동 전환 X)
        suggest_done=r.progress_pct >= 100 and entry is not None and entry.shelf is not Shelf.DONE,
    )
