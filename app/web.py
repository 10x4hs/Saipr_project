"""웹 화면 — 서재(홈) · 검색 · 리더. 서버 렌더링(Jinja2) + 리더만 작은 JS."""

from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
from app.sources.base import BookSource, SourceError

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# 위키문헌에 전문이 있는 한국 근대 단편 (모두 저자 사후 70년 경과)
FEATURED = [
    ("봄봄", "김유정", 1935),
    ("동백꽃", "김유정", 1936),
    ("운수 좋은 날", "현진건", 1924),
    ("메밀꽃 필 무렵", "이효석", 1936),
    ("날개", "이상", 1936),
    ("감자", "김동인", 1925),
    ("벙어리 삼룡이", "나도향", 1925),
    ("배따라기", "김동인", 1921),
]


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    imported = (await session.scalars(select(Book).where(Book.has_fulltext).order_by(Book.id.desc()))).all()
    return templates.TemplateResponse(request, "home.html", {"featured": FEATURED, "imported": imported})


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
    request: Request, book_id: int, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    book = await session.get(Book, book_id)
    if book is None or not book.has_fulltext:
        raise HTTPException(404, "책을 찾을 수 없어요")
    return templates.TemplateResponse(request, "reader.html", {"book": book})
