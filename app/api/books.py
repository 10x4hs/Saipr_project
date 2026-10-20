from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_book, get_http_client, get_sources, verify_csrf
from app.api.library import EntryOut, entry_out
from app.api.schemas import BookCard, UserMini, book_card, user_mini
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models import Book, Follow, LibraryEntry, Shelf, User
from app.services import book_info, catalog
from app.services import books as book_service
from app.services import library as lib
from app.services.pace import min_dwell_ms
from app.services.search import FULLTEXT_SOURCES, search_all
from app.sources.base import BookSource, SourceError

router = APIRouter(prefix="/api/v1/books", tags=["books"], dependencies=[Depends(verify_csrf)])


class BookHitOut(BaseModel):
    source: str
    external_id: str
    title: str
    authors: list[str]
    isbn13: str | None
    cover_url: str | None
    language: str | None
    has_fulltext: bool
    link: str | None
    also_in: list[str]


class SearchOut(BaseModel):
    items: list[BookHitOut]
    errors: dict[str, str]


class ImportIn(BaseModel):
    source: str
    external_id: str


class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_id: str
    title: str
    author: str | None
    language: str | None
    has_fulltext: bool
    total_chunks: int


class BookInfoOut(BookCard):
    description: str | None
    author_bio: str | None
    source_url: str | None
    wiki_url: str | None
    friends_reading: list[UserMini]
    my_entry: EntryOut | None
    total_chars: int


class ChunkOut(BaseModel):
    book_id: int
    chunk_index: int
    total_chunks: int
    text: str
    char_count: int
    min_dwell_ms: int


@router.get("", response_model=list[BookCard])
async def list_books(
    genre: Literal["소설", "시", "수필"] | None = None,
    sort: Literal["popular", "new"] = "popular",
    limit: int = Query(30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[BookCard]:
    """앱에 있는 책(전문 · 트래커). popular = 서재에 담은 사람이 많은 순, new = 최근에 들어온 순."""
    return [book_card(b, n) for b, n in await catalog.list_books(session, genre, sort, limit)]


@router.get("/search", response_model=SearchOut)
async def search_books(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=30),
    sources: dict[str, BookSource] = Depends(get_sources),
    settings: Settings = Depends(get_settings),
) -> SearchOut:
    result = await search_all(list(sources.values()), q, limit, settings.http_timeout_seconds)
    return SearchOut(
        items=[
            BookHitOut(
                source=h.meta.source,
                external_id=h.meta.external_id,
                title=h.meta.title,
                authors=list(h.meta.authors),
                isbn13=h.meta.isbn13,
                cover_url=h.meta.cover_url,
                language=h.meta.language,
                has_fulltext=h.meta.has_fulltext,
                link=h.meta.link,
                also_in=h.sources[1:],
            )
            for h in result.hits
        ],
        errors=result.errors,
    )


@router.post("/import", response_model=BookOut)
async def import_book(
    body: ImportIn,
    sources: dict[str, BookSource] = Depends(get_sources),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
) -> BookOut:
    src = sources.get(body.source)
    if src is None or body.source not in FULLTEXT_SOURCES:
        raise HTTPException(400, f"'{body.source}' is not a public-domain full-text source")
    try:
        book = await book_service.import_book(session, src, body.external_id)
    except SourceError as e:
        raise HTTPException(422, str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"upstream {body.source} failed: {type(e).__name__}") from e
    return BookOut.model_validate(book)


@router.get("/{book_id}", response_model=BookOut)
async def get_book_detail(book: Book = Depends(get_book)) -> BookOut:
    return BookOut.model_validate(book)


@router.get("/{book_id}/chunks/{chunk_index}", response_model=ChunkOut)
async def get_chunk(book_id: int, chunk_index: int, session: AsyncSession = Depends(get_session)) -> ChunkOut:
    found = await book_service.get_chunk(session, book_id, chunk_index)
    if found is None:
        raise HTTPException(404, "chunk not found")
    book, chunk = found
    return ChunkOut(
        book_id=book.id,
        chunk_index=chunk.chunk_index,
        total_chunks=book.total_chunks,
        text=chunk.text,
        char_count=chunk.char_count,
        min_dwell_ms=min_dwell_ms(chunk.text, book.language),
    )


@router.get("/{book_id}/info", response_model=BookInfoOut)
async def book_info_detail(
    book: Book = Depends(get_book),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> BookInfoOut:
    """책 소개 화면. 위키백과 요약은 처음 한 번 받아 캐시하고, 받지 못하면 null(오류 아님)."""
    await book_info.ensure_info(session, client, book)
    readers = (await catalog.readers_counts(session, [book.id]))[book.id]
    friends = await session.scalars(
        select(User)
        .join(Follow, Follow.followee_id == User.id)
        .join(LibraryEntry, LibraryEntry.user_id == User.id)
        .where(
            Follow.follower_id == user.id,
            LibraryEntry.book_id == book.id,
            LibraryEntry.shelf == Shelf.READING,
        )
        .order_by(LibraryEntry.updated_at.desc(), User.id)
        .limit(20)
    )
    entry = await lib.get_entry(session, user.id, book.id)
    return BookInfoOut(
        **book_card(book, readers).model_dump(),
        description=book.description,
        author_bio=book.author_bio,
        source_url=catalog.source_url(book),
        wiki_url=book.wiki_url,
        friends_reading=[user_mini(u) for u in friends],
        my_entry=entry_out(entry, book) if entry else None,
        total_chars=await catalog.total_chars(session, book.id),
    )
