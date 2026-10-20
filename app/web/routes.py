"""웹 화면 (Jinja2 서버 렌더링). 제품은 mobile/의 네이티브 앱이고, 웹에는 꼭 필요한 것만 남긴다.

남은 화면: 첫 화면(앱 안내) · 로그인/가입/로그아웃 · 소셜 로그인 · 초대 링크 미리보기 · 오류 화면.
"""

import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    csrf_token,
    get_http_client,
    login_session,
    logout_session,
    optional_user,
    verify_csrf,
)
from app.core.clock import aware, utcnow
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models import Book, User
from app.services import auth as auth_service
from app.services import oauth
from app.services import rooms as room_service
from app.web import view

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter(include_in_schema=False, dependencies=[Depends(verify_csrf)])
view.register(TEMPLATES.env)


def wants_html(request: Request) -> bool:
    return not request.url.path.startswith(("/api/", "/ws/"))


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def _back(request: Request, fallback: str = "/") -> str:
    ref = request.headers.get("referer")
    # 같은 사이트 안의 경로로만 돌아간다 (오픈 리다이렉트 방지)
    if ref and urlparse(ref).netloc == request.url.netloc:
        p = urlparse(ref)
        return p.path + (f"?{p.query}" if p.query else "")
    return fallback


def _safe_next(path: str | None) -> str:
    return path if path and path.startswith("/") and not path.startswith("//") else "/"


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


async def error_page(request: Request, exc: Exception) -> Response:
    flash(request, str(exc), "error")
    return redirect(_back(request))


async def http_error_page(request: Request, exc: HTTPException) -> Response:
    # 테스트에서 바꿔 끼운 세션 의존성도 그대로 따른다
    provider = request.app.dependency_overrides.get(get_session, get_session)
    async for session in provider():
        user = await optional_user(request, session)
        resp = render(request, "error.html", user, status=exc.status_code, detail=exc.detail)
        resp.status_code = exc.status_code
        return resp
    raise RuntimeError("unreachable")


def render(request: Request, name: str, user: User | None, **ctx: Any) -> HTMLResponse:
    ctx.update(
        user=user,
        csrf=csrf_token(request),
        flash=request.session.pop("flash", None),
        providers=oauth.enabled_providers(get_settings()),
    )
    return TEMPLATES.TemplateResponse(request, name, ctx)


# ── 첫 화면: 앱 안내 ───────────────────────────────────────


@router.get("/")
async def landing(request: Request, user: User | None = Depends(optional_user)):
    return render(request, "landing.html", user)


# ── 인증 ──────────────────────────────────────────────────


@router.get("/login")
async def login_page(request: Request, next: str = "/", user: User | None = Depends(optional_user)):
    if user:
        return redirect(_safe_next(next))
    return render(request, "login.html", None, next=_safe_next(next), errors={}, form={})


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    session: AsyncSession = Depends(get_session),
):
    user = await auth_service.authenticate(session, email, password)
    if user is None:
        return render(
            request,
            "login.html",
            None,
            next=_safe_next(next),
            errors={"form": "이메일 또는 비밀번호가 맞지 않아요."},
            form={"email": email},
        )
    login_session(request, user)
    return redirect(_safe_next(next))


@router.get("/signup")
async def signup_page(request: Request, next: str = "/"):
    return render(request, "signup.html", None, next=_safe_next(next), errors={}, form={})


@router.post("/signup")
async def signup_submit(
    request: Request,
    nickname: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    next: str = Form("/"),
    session: AsyncSession = Depends(get_session),
):
    try:
        user = await auth_service.signup(session, nickname, email, password, password_confirm)
    except auth_service.AuthError as e:
        # 실패 화면에 비밀번호는 다시 채우지 않는다
        return render(
            request,
            "signup.html",
            None,
            next=_safe_next(next),
            errors=e.errors,
            form={"nickname": nickname, "email": email},
        )
    login_session(request, user)
    flash(request, f"환영해요, {user.nickname}님!")
    return redirect(_safe_next(next))


@router.post("/logout")
async def logout(request: Request):
    logout_session(request)
    return redirect("/")


@router.get("/auth/{provider}/login")
async def oauth_start(
    request: Request, provider: str, next: str = "/", settings: Settings = Depends(get_settings)
):
    p = oauth.enabled_providers(settings).get(provider)
    if p is None:
        raise HTTPException(404, "사용할 수 없는 로그인 방식이에요.")
    state = secrets.token_urlsafe(24)
    # state에 복귀 경로를 묶어 둔다 — 초대 링크로 왔다면 로그인 후 그 미리보기로 돌아간다 (PRD AUTH-01)
    request.session["oauth"] = {"state": state, "provider": provider, "next": _safe_next(next)}
    return RedirectResponse(oauth.authorize_url(p, oauth.redirect_uri(settings, provider), state))


@router.get("/auth/{provider}/callback")
async def oauth_callback(
    request: Request,
    provider: str,
    code: str = "",
    state: str = "",
    settings: Settings = Depends(get_settings),
    client: httpx.AsyncClient = Depends(get_http_client),
    session: AsyncSession = Depends(get_session),
):
    saved = request.session.pop("oauth", None) or {}
    p = oauth.enabled_providers(settings).get(provider)
    if p is None or not code or not state or saved.get("state") != state or saved.get("provider") != provider:
        flash(request, "로그인 요청이 올바르지 않아요. 다시 시도해 주세요.", "error")
        return redirect("/login")
    try:
        token = await oauth.exchange_code(client, p, code, oauth.redirect_uri(settings, provider), state)
        profile = await oauth.fetch_profile(client, p, token)
    except (httpx.HTTPError, KeyError, ValueError):
        flash(request, f"{p.label} 로그인에 실패했어요.", "error")
        return redirect("/login")
    user = await auth_service.oauth_user(
        session, profile.provider, profile.id, profile.nickname, profile.email
    )
    login_session(request, user)
    return redirect(saved.get("next", "/"))


# ── 초대 링크 미리보기 ──────────────────────────────────────


@router.get("/r/{code}")
async def invite_preview(
    request: Request,
    code: str,
    user: User | None = Depends(optional_user),
    session: AsyncSession = Depends(get_session),
):
    """초대 링크. 로그인 전에도 방 미리보기와 초대 코드를 보여 준다 — 참여는 앱에서 한다 (PRD Story 6)."""
    room = await room_service.by_code(session, code)
    if room is None or room.archived:
        raise HTTPException(404, "초대 링크를 찾을 수 없어요.")
    return render(
        request,
        "invite.html",
        user,
        room=room,
        book=await session.get(Book, room.book_id),
        code=room.invite_code,
        expired=bool(room.invite_expires_at and aware(room.invite_expires_at) < utcnow()),
        joined=bool(user and await room_service.is_member(session, room.id, user.id)),
        members=await room_service.members(session, room),
    )
