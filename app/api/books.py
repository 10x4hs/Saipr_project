import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_book, get_sources, verify_csrf
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models import Book, User
from app.services import books as book_service
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
