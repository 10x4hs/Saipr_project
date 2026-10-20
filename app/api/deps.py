import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import csrf_matches, new_csrf_token
from app.db.session import get_session
from app.models import Book, User
from app.sources.base import BookSource
from app.sources.registry import build_sources

SESSION_USER = "uid"
SESSION_CSRF = "csrf"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def get_sources(
    client: httpx.AsyncClient = Depends(get_http_client),
    settings: Settings = Depends(get_settings),
) -> dict[str, BookSource]:
    return build_sources(client, settings)


# ── 세션 · 로그인 ───────────────────────────────────────────


def csrf_token(request: Request) -> str:
    """세션마다 하나의 CSRF 토큰. 템플릿과 /api/v1/auth/csrf가 이 값을 내준다."""
    token = request.session.get(SESSION_CSRF)
    if not token:
        token = request.session[SESSION_CSRF] = new_csrf_token()
    return token


def login_session(request: Request, user: User) -> None:
    # 로그인 때 세션 내용을 통째로 갈아 끼워 세션 고정 공격을 막는다 (CSRF 토큰도 새로 발급)
    request.session.clear()
    request.session[SESSION_USER] = user.id
    request.session[SESSION_CSRF] = new_csrf_token()


def logout_session(request: Request) -> None:
    request.session.clear()


async def optional_user(request: Request, session: AsyncSession = Depends(get_session)) -> User | None:
    uid = request.session.get(SESSION_USER)
    if uid is None:
        return None
    user = await session.get(User, uid)
    if user is None:
        request.session.clear()
    return user


async def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "로그인이 필요해요.")
    return user


async def verify_csrf(request: Request) -> None:
    """쿠키 세션을 쓰므로 상태를 바꾸는 요청은 토큰을 확인한다. 헤더(JS) 또는 폼 필드(HTML 폼)."""
    if request.method not in UNSAFE:
        return
    given = request.headers.get(CSRF_HEADER)
    if given is None and request.headers.get("content-type", "").startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        given = (await request.form()).get(CSRF_FIELD)
    if not csrf_matches(request.session.get(SESSION_CSRF), given if isinstance(given, str) else None):
        raise HTTPException(403, "CSRF 토큰이 없거나 맞지 않아요. 페이지를 새로고침해 주세요.")


async def get_book(book_id: int, session: AsyncSession = Depends(get_session)) -> Book:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(404, "책을 찾을 수 없어요.")
    return book
