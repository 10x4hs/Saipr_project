import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import csrf_matches, new_csrf_token
from app.db.session import get_session
from app.models import ApiToken, Book, User
from app.services import tokens as token_service
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


# ── Bearer 토큰 (네이티브 앱) ──────────────────────────────────

_UNSET = object()
BAD_TOKEN = "로그인이 만료됐어요. 다시 로그인해 주세요."


def bearer_of(request: Request) -> str | None:
    """Authorization: Bearer <token>의 토큰. 헤더가 없거나 다른 방식이면 None."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip()


async def bearer_auth(request: Request, session: AsyncSession) -> tuple[ApiToken, User] | None:
    """요청의 Bearer 토큰을 한 번만 확인하고 결과를 요청에 붙여 둔다(CSRF 검사와 사용자 조회가 같이 쓴다)."""
    cached = getattr(request.state, "bearer", _UNSET)
    if cached is not _UNSET:
        return cached
    raw = bearer_of(request)
    found = await token_service.lookup(session, raw) if raw is not None else None
    request.state.bearer = found
    return found


async def optional_user(request: Request, session: AsyncSession = Depends(get_session)) -> User | None:
    if bearer_of(request) is not None:
        # 토큰을 보냈으면 쿠키로 되돌아가지 않는다. 틀린 토큰은 로그인하지 않은 것과 같다
        found = await bearer_auth(request, session)
        if found is None:
            raise HTTPException(401, BAD_TOKEN)
        return found[1]
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


async def verify_csrf(request: Request, session: AsyncSession = Depends(get_session)) -> None:
    """쿠키 세션을 쓰므로 상태를 바꾸는 요청은 토큰을 확인한다. 헤더(JS) 또는 폼 필드(HTML 폼).

    유효한 Bearer 토큰으로 인증한 요청은 건너뛴다. 브라우저가 다른 사이트 요청에 자동으로 붙이는 것은
    쿠키뿐이고 Authorization 헤더는 붙이지 않으므로 CSRF가 성립하지 않는다.
    쿠키 세션만 있는 요청은 지금처럼 반드시 확인한다.
    """
    if request.method not in UNSAFE:
        return
    if bearer_of(request) is not None:
        if await bearer_auth(request, session) is None:
            raise HTTPException(401, BAD_TOKEN)
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
