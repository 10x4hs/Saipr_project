"""웹 화면 — 서재(홈) · 검색 · 파일 올리기 · 리더. 서버 렌더링(Jinja2) + 리더만 작은 JS."""

import json
import secrets
from pathlib import Path

import httpx
from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_sources
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models import Book
from app.services import books as book_service
from app.services.search import FULLTEXT_SOURCES, search_all
from app.services.uploads import MAX_UPLOAD_BYTES, parse_upload
from app.sources.base import BookSource, SourceError

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

READER_KEY = "reader_key"
KEY_MAX_AGE = 60 * 60 * 24 * 365 * 2

# 서가 카탈로그 — scripts/build_catalog.py로 만든다 (퍼블릭 도메인 확인된 작품만)
CATALOG: list[dict] = json.loads((Path(__file__).parent / "data" / "catalog.json").read_text())
GENRE_ORDER = ["단편소설", "장편소설", "중편소설", "동화", "수필", "시집", "세계 고전"]
SHELVES = {g: [b for b in CATALOG if b["genre"] == g] for g in GENRE_ORDER}
SHELVES = {g: books for g, books in SHELVES.items() if books}
PREVIEW = 8


def _remember_key(response: RedirectResponse, key: str) -> None:
    response.set_cookie(READER_KEY, key, max_age=KEY_MAX_AGE, httponly=True, samesite="lax")


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    session: AsyncSession = Depends(get_session),
    reader_key: str | None = Cookie(None),
) -> HTMLResponse:
    public = (
        await session.scalars(
            select(Book).where(Book.has_fulltext, Book.owner_key_hash.is_(None)).order_by(Book.id.desc())
        )
    ).all()
    uploads = await book_service.uploads_of(session, reader_key)
    return templates.TemplateResponse(
        request,
        "home.html",
        {"shelves": SHELVES, "preview": PREVIEW, "total": len(CATALOG), "library": [*uploads, *public]},
    )


@router.get("/shelf/{genre}", response_class=HTMLResponse)
async def shelf(request: Request, genre: str) -> HTMLResponse:
    if genre not in SHELVES:
        raise HTTPException(404, "서가를 찾을 수 없어요")
    return templates.TemplateResponse(request, "shelf.html", {"genre": genre, "books": SHELVES[genre]})


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query("", max_length=100),
    sources: dict[str, BookSource] = Depends(get_sources),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    readable, others, errors = [], [], {}
    if q.strip():
        result = await search_all(list(sources.values()), q.strip(), 20, settings.http_timeout_seconds)
        errors = result.errors
        for h in result.hits:
            (readable if h.meta.has_fulltext else others).append(h.meta)
    return templates.TemplateResponse(
        request,
        "search.html",
        {"q": q, "readable": readable, "others": others, "errors": errors},
    )


@router.get("/upload", response_class=HTMLResponse)
async def upload_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "upload.html", {"error": None})


@router.post("/upload", response_class=HTMLResponse, response_model=None)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    reader_key: str | None = Cookie(None),
) -> HTMLResponse | RedirectResponse:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        parsed = parse_upload(file.filename or "untitled.txt", data)
    except SourceError as e:
        return templates.TemplateResponse(request, "upload.html", {"error": str(e)}, status_code=422)
    key = reader_key or secrets.token_urlsafe(32)
    book = await book_service.save_upload(session, parsed, key)
    response = RedirectResponse(f"/books/{book.id}", status_code=303)
    _remember_key(response, key)
    return response


@router.get("/open/{source}/{external_id:path}")
async def open_book(
    source: str,
    external_id: str,
    sources: dict[str, BookSource] = Depends(get_sources),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """퍼블릭 도메인 전문을 가져와(이미 있으면 캐시) 리더로 보낸다."""
    src = sources.get(source)
    if src is None or source not in FULLTEXT_SOURCES:
        raise HTTPException(400, "이 책은 앱에서 본문을 제공하지 않아요")
    try:
        book = await book_service.import_book(session, src, external_id)
    except SourceError as e:
        raise HTTPException(422, f"본문을 가져오지 못했어요: {e}") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"{source} 응답이 없어요 ({type(e).__name__})") from e
    return RedirectResponse(f"/books/{book.id}", status_code=303)


@router.get("/books/{book_id}", response_class=HTMLResponse)
async def reader(
    request: Request,
    book_id: int,
    session: AsyncSession = Depends(get_session),
    reader_key: str | None = Cookie(None),
) -> HTMLResponse:
    book = await session.get(Book, book_id)
    if book is None or not book_service.can_read(book, reader_key):
        raise HTTPException(404, "책을 찾을 수 없어요")
    return templates.TemplateResponse(request, "reader.html", {"book": book})
