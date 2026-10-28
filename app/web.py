"""웹 화면 — 서재(홈) · 검색 · 파일 올리기 · 리더. 서버 렌더링(Jinja2) + 리더만 작은 JS."""

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

# (source, external_id, 제목, 저자, 연도) — 모두 저자 사후 70년이 지난 작품
SHELVES = {
    "한국 근대 단편": [
        ("wikisource", "봄봄", "봄봄", "김유정", 1935),
        ("wikisource", "동백꽃", "동백꽃", "김유정", 1936),
        ("wikisource", "만무방", "만무방", "김유정", 1935),
        ("wikisource", "운수 좋은 날", "운수 좋은 날", "현진건", 1924),
        ("wikisource", "B사감과 러브레터", "B사감과 러브레터", "현진건", 1925),
        ("wikisource", "고향 (현진건)", "고향", "현진건", 1926),
        ("wikisource", "메밀꽃 필 무렵", "메밀꽃 필 무렵", "이효석", 1936),
        ("wikisource", "날개", "날개", "이상", 1936),
        ("wikisource", "감자", "감자", "김동인", 1925),
        ("wikisource", "배따라기", "배따라기", "김동인", 1921),
        ("wikisource", "광염 소나타", "광염 소나타", "김동인", 1930),
        ("wikisource", "벙어리 삼룡이", "벙어리 삼룡이", "나도향", 1925),
        ("wikisource", "물레방아", "물레방아", "나도향", 1925),
        ("wikisource", "레디메이드 인생", "레디메이드 인생", "채만식", 1934),
        ("wikisource", "치숙", "치숙", "채만식", 1938),
        ("wikisource", "탈출기", "탈출기", "최서해", 1925),
    ],
    "영어 고전": [
        ("gutendex", "1342", "Pride and Prejudice", "Jane Austen", 1813),
        ("gutendex", "11", "Alice's Adventures in Wonderland", "Lewis Carroll", 1865),
        ("gutendex", "84", "Frankenstein", "Mary Shelley", 1818),
        ("gutendex", "1661", "The Adventures of Sherlock Holmes", "Arthur Conan Doyle", 1892),
        ("gutendex", "5200", "Metamorphosis", "Franz Kafka", 1915),
        ("gutendex", "64317", "The Great Gatsby", "F. Scott Fitzgerald", 1925),
    ],
}


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
        request, "home.html", {"shelves": SHELVES, "library": [*uploads, *public]}
    )


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
