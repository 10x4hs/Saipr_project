import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_sources
from app.auth import check_csrf, current_user, require_api_user
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models import Book, User
from app.realtime import broker
from app.services import books as book_service
from app.services import social
from app.services.search import FULLTEXT_SOURCES, search_all
from app.sources.base import BookSource, SourceError

router = APIRouter(prefix="/api/v1/books", tags=["books"])


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


class ChunkOut(BaseModel):
    book_id: int
    chunk_index: int
    total_chunks: int
    text: str
    char_count: int
    min_dwell_ms: int


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
    request: Request,
    x_csrf_token: str | None = Header(None),
    sources: dict[str, BookSource] = Depends(get_sources),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_api_user),
) -> BookOut:
    check_csrf(request, x_csrf_token)  # 외부 요청과 DB 저장을 일으키므로 로그인한 화면에서만
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


@router.get("/{book_id}/chunks/{chunk_index}", response_model=ChunkOut)
async def get_chunk(
    book_id: int,
    chunk_index: int,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
) -> ChunkOut:
    found = await book_service.get_chunk(session, book_id, chunk_index)
    # 남이 올린 책은 존재 여부도 드러내지 않도록 404로 통일
    if found is None or not book_service.can_read(found[0], user.id if user else None):
        raise HTTPException(404, "chunk not found")
    book, chunk = found
    return ChunkOut(
        book_id=book.id,
        chunk_index=chunk.chunk_index,
        total_chunks=book.total_chunks,
        text=chunk.text,
        char_count=chunk.char_count,
        min_dwell_ms=book_service.required_dwell_ms(chunk.text, book.language),
    )


class ProgressIn(BaseModel):
    chunk_index: int
    verified: bool = False


class ProgressOut(BaseModel):
    current_chunk: int
    verified_chunk: int
    progress_pct: int
    shelf: str


@router.put("/{book_id}/progress", response_model=ProgressOut)
async def put_progress(
    book_id: int,
    body: ProgressIn,
    request: Request,
    x_csrf_token: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_api_user),
) -> ProgressOut:
    check_csrf(request, x_csrf_token)
    book = await session.get(Book, book_id)
    if book is None or not book_service.can_read(book, user.id):
        raise HTTPException(404, "book not found")
    before = await book_service.shelve(session, user.id, book.id)
    was_verified = before.verified_chunk
    e = await book_service.record_progress(session, user.id, book, body.chunk_index, body.verified)
    # 같은 방 친구들에게: 검증 위치가 올라갔거나 다른 쪽으로 옮겼을 때
    others = await social.circle(session, user.id, book.id) - {user.id}
    await broker.publish(
        book.id,
        others,
        {
            "type": "progress.updated",
            "user_id": user.id,
            "nickname": user.nickname,
            "current_chunk": e.current_chunk,
            "verified_chunk": e.verified_chunk,
            "advanced": e.verified_chunk > was_verified,
        },
    )
    return ProgressOut(
        current_chunk=e.current_chunk,
        verified_chunk=e.verified_chunk,
        progress_pct=e.progress_pct,
        shelf=e.shelf,
    )
