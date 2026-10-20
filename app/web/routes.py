"""웹 화면 (Jinja2 서버 렌더링). 폼은 POST → 303 리다이렉트, 실시간 부분만 static/js가 담당한다.

화면 구성은 PRD 9장 정보 구조를 따른다: 홈 · 검색/상세 · 리더 · 읽기방 · 배틀 · 리더보드(팀) · 내 정보.
"""

import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    csrf_token,
    get_http_client,
    get_sources,
    login_session,
    logout_session,
    optional_user,
    verify_csrf,
)
from app.core.clock import KST, aware, utcnow
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models import Battle, BattleType, Book, BookChunk, Room, RoomMode, Shelf, Team, User
from app.services import auth as auth_service
from app.services import battles as battle_service
from app.services import books as book_service
from app.services import library as lib
from app.services import notifications as noti
from app.services import oauth
from app.services import points as point_service
from app.services import reactions as reaction_service
from app.services import rooms as room_service
from app.services import teams as team_service
from app.services.pace import min_dwell_ms
from app.services.search import FULLTEXT_SOURCES, search_all
from app.sources.base import BookMeta, BookSource, SourceError
from app.web import view

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter(include_in_schema=False, dependencies=[Depends(verify_csrf)])

SHELF_LABEL = {Shelf.WANT: "읽고 싶은", Shelf.READING: "읽는 중", Shelf.DONE: "완독"}
LEAGUE_TIERS = ("브론즈", "실버", "골드", "다이아")


def _kst(dt: datetime | None, fmt: str = "%m.%d %H:%M") -> str:
    return aware(dt).astimezone(KST).strftime(fmt) if dt else ""


TEMPLATES.env.filters["kst"] = _kst
TEMPLATES.env.globals["SHELF_LABEL"] = SHELF_LABEL
TEMPLATES.env.globals["EMOJIS"] = reaction_service.EMOJIS
view.register(TEMPLATES.env)


class LoginRequired(Exception):
    pass


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
        resp = await render(request, "error.html", user, session, status=exc.status_code, detail=exc.detail)
        resp.status_code = exc.status_code
        return resp
    raise RuntimeError("unreachable")


async def render(
    request: Request, name: str, user: User | None, session: AsyncSession, **ctx: Any
) -> HTMLResponse:
    settings = get_settings()
    path = request.url.path
    ctx.setdefault("tab", _tab_for(path))
    ctx.update(
        user=user,
        csrf=csrf_token(request),
        flash=request.session.pop("flash", None),
        unread=await noti.unread_count(session, user.id) if user else 0,
        providers=oauth.enabled_providers(settings),
        path=path,
        clock=view.clock(),
    )
    return TEMPLATES.TemplateResponse(request, name, ctx)


def _tab_for(path: str) -> str | None:
    """하단 탭바에서 켜 둘 탭. 책·읽기방·팀 상세는 그 화면을 연 탭에 속한다."""
    if path == "/":
        return "home"
    if path.startswith(("/search", "/books")):
        return "search"
    if path.startswith(("/rooms", "/r/")):
        return "rooms"
    if path.startswith(("/teams", "/battles")):
        return "league"
    return None


async def need_user(request: Request, user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise LoginRequired
    return user


def login_redirect(request: Request) -> RedirectResponse:
    nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return redirect(f"/login?next={quote(nxt)}")


# ── PWA: 서비스 워커 · 매니페스트 · 오프라인 화면 ──────────────────

STATIC = Path(__file__).parent / "static"

MANIFEST = {
    "name": "함께읽기",
    "short_name": "함께읽기",
    "description": "같은 책을 각자의 속도로 — 친구의 진행률과 반응이 겹쳐 보이는 소셜 독서",
    "lang": "ko",
    "start_url": "/?source=pwa",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#9ea3a9",
    "theme_color": "#6f767f",
    "icons": [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {
            "src": "/static/icons/maskable-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ],
    "shortcuts": [
        {
            "name": "이어 읽기",
            "url": "/?source=shortcut",
            "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}],
        },
        {
            "name": "읽기방",
            "url": "/rooms",
            "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}],
        },
        {
            "name": "이번 주 리그",
            "url": "/teams",
            "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}],
        },
    ],
}


@router.get("/sw.js")
async def service_worker() -> Response:
    # 사이트 루트에서 제공해야 모든 화면을 맡을 수 있다. 새 버전을 바로 받도록 캐시하지 않는다.
    return Response(
        (STATIC / "sw.js").read_text(encoding="utf-8"),
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@router.get("/manifest.webmanifest")
async def manifest() -> Response:
    return Response(json.dumps(MANIFEST, ensure_ascii=False), media_type="application/manifest+json")


@router.get("/offline")
async def offline_page(request: Request, session: AsyncSession = Depends(get_session)):
    return await render(request, "offline.html", None, session)


# ── 인증 ──────────────────────────────────────────────────


@router.get("/login")
async def login_page(
    request: Request,
    next: str = "/",
    user: User | None = Depends(optional_user),
    session: AsyncSession = Depends(get_session),
):
    if user:
        return redirect(_safe_next(next))
    return await render(request, "login.html", None, session, next=_safe_next(next), errors={}, form={})


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
        return await render(
            request,
            "login.html",
            None,
            session,
            next=_safe_next(next),
            errors={"form": "이메일 또는 비밀번호가 맞지 않아요."},
            form={"email": email},
        )
    login_session(request, user)
    return redirect(_safe_next(next))


@router.get("/signup")
async def signup_page(request: Request, next: str = "/", session: AsyncSession = Depends(get_session)):
    return await render(request, "signup.html", None, session, next=_safe_next(next), errors={}, form={})


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
        return await render(
            request,
            "signup.html",
            None,
            session,
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
    return redirect("/login")


@router.get("/auth/{provider}/login")
async def oauth_start(
    request: Request, provider: str, next: str = "/", settings: Settings = Depends(get_settings)
):
    p = oauth.enabled_providers(settings).get(provider)
    if p is None:
        raise HTTPException(404, "사용할 수 없는 로그인 방식이에요.")
    state = secrets.token_urlsafe(24)
    # state에 복귀 경로를 묶어 둔다 — 초대 링크로 왔다면 로그인 후 그 방으로 돌아간다 (PRD AUTH-01)
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


# ── 홈 · 서재 ──────────────────────────────────────────────


def _friend_line(ms: list, me: int) -> str:
    """읽기방 카드의 한 줄 소식: 가장 앞선 친구를 알려 준다."""
    friends = [m for m in ms if m.user_id != me]
    if not friends:
        return "친구를 초대해서 같이 읽어요"
    lead = max(friends, key=lambda m: (m.progress_pct, -m.user_id))
    if lead.progress_pct == 0:
        return f"{lead.nickname}님과 함께 읽는 중이에요"
    return f"{lead.nickname}님이 {lead.progress_pct}%까지 읽었어요"


async def _race_card(session: AsyncSession, battle: Battle, user_id: int) -> dict:
    a, b = await battle_service.sides(session, battle)
    mine, theirs = (a, b) if any(u == user_id for u, _, _ in a.members) else (b, a)
    gap = round(mine.average - theirs.average, 1)
    if gap > 0:
        line = f"우리 팀이 {gap:g}청크 앞서는 중"
    elif gap < 0:
        line = f"우리 팀이 {-gap:g}청크 뒤지는 중"
    else:
        line = "막상막하예요"
    book = await session.get(Book, battle.book_id)
    return {"battle": battle, "mine": mine, "theirs": theirs, "line": line, "book": book}


async def room_cards(session: AsyncSession, user_id: int, limit: int | None = None) -> list[dict]:
    cards = []
    for room, book in (await room_service.rooms_of(session, user_id))[:limit]:
        ms = await room_service.members(session, room)
        cards.append({"room": room, "book": book, "members": ms, "line": _friend_line(ms, user_id)})
    return cards


@router.get("/")
async def home(
    request: Request, user: User = Depends(need_user), session: AsyncSession = Depends(get_session)
):
    entries = await lib.list_entries(session, user.id)
    # 이어 읽기: 가장 최근에 읽던 책 (읽는 중 → 읽고 싶은 순)
    current = next(((e, b) for e, b in entries if e.shelf is Shelf.READING), None) or next(
        ((e, b) for e, b in entries if e.shelf is Shelf.WANT), None
    )
    now = utcnow()
    races = [
        await _race_card(session, b, user.id)
        for b in await battle_service.battles_of(session, user.id)
        if battle_service.status_at(b, now).value != "finished"
    ]
    return await render(
        request,
        "home.html",
        user,
        session,
        current=current,
        streak=await point_service.streak_days(session, user.id),
        rooms=await room_cards(session, user.id, 3),
        races=races[:2],
        tab="home",
    )


@router.get("/rooms")
async def rooms_page(
    request: Request, user: User = Depends(need_user), session: AsyncSession = Depends(get_session)
):
    return await render(
        request, "rooms.html", user, session, rooms=await room_cards(session, user.id), tab="rooms"
    )


@router.post("/rooms/join")
async def join_by_link(
    request: Request,
    link: str = Form(""),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    """초대 링크(또는 코드)를 붙여 넣어 입장."""
    code = link.strip().rstrip("/").rsplit("/", 1)[-1]
    room = await room_service.join(session, code, user)
    return redirect(f"/rooms/{room.id}")


@router.post("/library/{book_id}/shelf")
async def set_shelf(
    request: Request,
    book_id: int,
    shelf: Shelf = Form(...),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Book, book_id) is None:
        raise HTTPException(404)
    await lib.set_shelf(session, user.id, book_id, shelf)
    flash(request, f"서재에 ‘{SHELF_LABEL[shelf]}’(으)로 담았어요.")
    return redirect(_back(request, f"/books/{book_id}"))


@router.post("/library/{book_id}/progress")
async def set_progress(
    request: Request,
    book_id: int,
    progress_pct: str = Form(""),
    current_page: str = Form(""),
    total_pages: str = Form(""),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(404)
    try:
        if current_page.strip() and total_pages.strip():
            pct = lib.pct_from_pages(int(current_page), int(total_pages))
        else:
            pct = int(progress_pct)
    except ValueError as e:
        raise lib.LibraryError("숫자로 입력해 주세요.") from e
    await lib.set_tracker_progress(session, user.id, book, pct)
    flash(request, f"진행률을 {pct}%로 기록했어요." + (" 완독으로 옮길까요?" if pct >= 100 else ""))
    return redirect(_back(request, f"/books/{book_id}"))


# ── 검색 · 도서 ────────────────────────────────────────────


@router.get("/search")
async def search_page(
    request: Request,
    q: str = "",
    f: str = "all",
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
    sources: dict[str, BookSource] = Depends(get_sources),
    settings: Settings = Depends(get_settings),
):
    """검색어가 없으면 내 서재, 있으면 통합 검색. f=full(전문 읽기) · track(진행률 기록)으로 거른다."""
    q = q.strip()[:100]
    hits, errors, local = [], {}, []
    if q:
        result = await search_all(list(sources.values()), q, 10, settings.http_timeout_seconds)
        errors = result.errors
        local = list(
            await session.scalars(
                select(Book).where(Book.title.contains(q) | Book.author.contains(q)).limit(5)
            )
        )
        known = {(b.source, b.external_id) for b in local}
        hits = [h for h in result.hits if (h.meta.source, h.meta.external_id) not in known]
        if f == "full":
            hits, local = [h for h in hits if h.meta.has_fulltext], [b for b in local if b.has_fulltext]
        elif f == "track":
            hits, local = (
                [h for h in hits if not h.meta.has_fulltext],
                [b for b in local if not b.has_fulltext],
            )
    shelf = [] if q else await lib.list_entries(session, user.id)
    return await render(
        request,
        "search.html",
        user,
        session,
        q=q,
        f=f,
        hits=hits,
        errors=errors,
        local=local,
        shelf=shelf,
        tab="search",
    )


@router.post("/books/import")
async def import_book(
    request: Request,
    source: str = Form(...),
    external_id: str = Form(...),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
    sources: dict[str, BookSource] = Depends(get_sources),
):
    src = sources.get(source)
    if src is None or source not in FULLTEXT_SOURCES:
        raise lib.LibraryError("본문을 가져올 수 없는 소스예요.")
    try:
        book = await book_service.import_book(session, src, external_id)
    except SourceError as e:
        raise lib.LibraryError(f"본문을 가져오지 못했어요: {e}") from e
    except httpx.HTTPError as e:
        raise lib.LibraryError(f"{source} 서버가 응답하지 않아요. 잠시 후 다시 시도해 주세요.") from e
    await lib.ensure_entry(session, user.id, book.id, Shelf.WANT)
    await session.commit()
    return redirect(f"/books/{book.id}")


@router.post("/books/track")
async def track_book(
    request: Request,
    source: str = Form(...),
    external_id: str = Form(...),
    title: str = Form(...),
    authors: str = Form(""),
    isbn13: str = Form(""),
    cover_url: str = Form(""),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    if source in FULLTEXT_SOURCES:
        raise lib.LibraryError("이 책은 앱 안에서 읽을 수 있어요. ‘전문 가져오기’를 눌러 주세요.")
    # 그 밖의 소스 검사는 register_tracker_book이 한다 (API와 같은 규칙)
    meta = BookMeta(
        source=source[:20],
        external_id=external_id,
        title=title,
        authors=tuple(a.strip() for a in authors.split(",") if a.strip()),
        isbn13=isbn13 or None,
        cover_url=cover_url or None,
        has_fulltext=False,
    )
    book = await lib.register_tracker_book(session, meta)
    await lib.ensure_entry(session, user.id, book.id, Shelf.WANT)
    await session.commit()
    flash(request, "트래커 모드로 서재에 담았어요. 진행률을 직접 기록해 주세요.")
    return redirect(f"/books/{book.id}")


@router.get("/books/{book_id}")
async def book_page(
    request: Request,
    book_id: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(404, "책을 찾을 수 없어요.")
    entry = await lib.get_entry(session, user.id, book.id)
    my_rooms = [r for r, b in await room_service.rooms_of(session, user.id) if b.id == book.id]
    preview = None
    if book.has_fulltext:
        preview = await session.scalar(
            select(BookChunk.text).where(BookChunk.book_id == book.id, BookChunk.chunk_index == 0)
        )
    return await render(
        request,
        "book.html",
        user,
        session,
        book=book,
        entry=entry,
        rooms=my_rooms,
        preview=(preview or "")[:280],
        teams=await team_service.teams_of(session, user.id),
    )


@router.get("/books/{book_id}/read")
async def reader(
    request: Request,
    book_id: int,
    chunk: int | None = None,
    room: int | None = None,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    book = await session.get(Book, book_id)
    if book is None or not book.has_fulltext:
        raise HTTPException(404, "앱 안에서 읽을 수 있는 책이 아니에요.")
    entry = await lib.ensure_entry(session, user.id, book.id, Shelf.READING)
    await session.commit()
    start = chunk if chunk is not None else max(0, entry.verified_chunk + 1)
    start = min(max(0, start), book.total_chunks - 1)
    # 함께 읽는 방: 지정한 방이 없으면 이 책의 첫 번째 방
    rooms_here = [r for r, b in await room_service.rooms_of(session, user.id) if b.id == book.id]
    current = next((r for r in rooms_here if r.id == room), rooms_here[0] if rooms_here else None)
    members = await room_service.members(session, current) if current else []
    return await render(
        request,
        "reader.html",
        user,
        session,
        book=book,
        entry=entry,
        start=start,
        room=current,
        rooms=rooms_here,
        members=members,
    )


@router.get("/books/{book_id}/chunk/{index}")
async def chunk_fragment(
    request: Request,
    book_id: int,
    index: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    """리더가 스크롤하면서 불러오는 청크 조각 (JSON)."""
    found = await book_service.get_chunk(session, book_id, index)
    if found is None:
        raise HTTPException(404)
    book, c = found
    return {
        "chunk_index": c.chunk_index,
        "paragraphs": [p for p in c.text.split("\n\n") if p.strip()],
        "min_dwell_ms": min_dwell_ms(c.text, book.language),
        "total_chunks": book.total_chunks,
    }


# ── 읽기방 ─────────────────────────────────────────────────


@router.post("/rooms")
async def create_room(
    request: Request,
    book_id: int = Form(...),
    name: str = Form(...),
    mode: RoomMode = Form(RoomMode.ASYNC),
    ends_on: str = Form(""),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(404)
    ends_at = None
    if ends_on:
        try:
            local_end = datetime.fromisoformat(ends_on).replace(tzinfo=KST) + timedelta(hours=23, minutes=59)
            ends_at = aware(local_end)
        except ValueError as e:
            raise room_service.RoomError("종료일 형식이 올바르지 않아요.") from e
    room = await room_service.create_room(session, user, book, name, mode, ends_at)
    flash(request, "방을 만들었어요. 초대 링크를 친구에게 보내 주세요!")
    return redirect(f"/rooms/{room.id}")


async def _member_room(session: AsyncSession, room_id: int, user: User) -> Room:
    room = await session.get(Room, room_id)
    if room is None or not await room_service.is_member(session, room_id, user.id):
        raise HTTPException(404, "방을 찾을 수 없어요.")
    return room


@router.get("/rooms/{room_id}")
async def room_page(
    request: Request,
    room_id: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    room = await _member_room(session, room_id, user)
    book = await session.get(Book, room.book_id)
    members = await room_service.members(session, room)
    counts = await team_service.verified_counts(
        session, [m.user_id for m in members], aware(room.created_at), book_id=room.book_id
    )
    race = sorted(members, key=lambda m: (-counts[m.user_id], m.user_id))
    feed = await reaction_service.feed(session, user, book, room)
    invite_url = f"{get_settings().public_base_url.rstrip('/')}/r/{room.invite_code}"
    return await render(
        request,
        "room.html",
        user,
        session,
        room=room,
        book=book,
        members=members,
        race=race,
        counts=counts,
        feed=feed,
        invite_url=invite_url,
        now=utcnow(),
    )


@router.post("/rooms/{room_id}/invite")
async def regenerate_invite(
    request: Request,
    room_id: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    await room_service.regenerate_invite(session, await _member_room(session, room_id, user), user)
    flash(request, "새 초대 링크를 만들었어요. 이전 링크는 더 이상 쓸 수 없어요.")
    return redirect(f"/rooms/{room_id}")


@router.post("/rooms/{room_id}/leave")
async def leave_room(
    request: Request,
    room_id: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    await room_service.leave(session, await _member_room(session, room_id, user), user)
    flash(request, "방에서 나왔어요.")
    return redirect("/")


@router.get("/r/{code}")
async def invite_preview(
    request: Request,
    code: str,
    user: User | None = Depends(optional_user),
    session: AsyncSession = Depends(get_session),
):
    """초대 링크. 로그인 전에도 방 미리보기를 보여 준다 (PRD Story 6)."""
    room = await room_service.by_code(session, code)
    if room is None or room.archived:
        raise HTTPException(404, "초대 링크를 찾을 수 없어요.")
    if user and await room_service.is_member(session, room.id, user.id):
        return redirect(f"/rooms/{room.id}")
    book = await session.get(Book, room.book_id)
    expired = bool(room.invite_expires_at and aware(room.invite_expires_at) < utcnow())
    return await render(
        request,
        "invite.html",
        user,
        session,
        room=room,
        book=book,
        code=code,
        expired=expired,
        members=await room_service.members(session, room),
    )


@router.post("/r/{code}/join")
async def invite_join(
    request: Request, code: str, user: User = Depends(need_user), session: AsyncSession = Depends(get_session)
):
    room = await room_service.join(session, code, user)
    return redirect(f"/rooms/{room.id}")


# ── 팀 · 리그 · 배틀 ────────────────────────────────────────


@router.get("/teams")
async def teams_page(
    request: Request, user: User = Depends(need_user), session: AsyncSession = Depends(get_session)
):
    mine = await team_service.teams_of(session, user.id)
    my_ids = {t.id for t in mine}
    leagues = team_service.build_leagues(await team_service.weekly_scores(session))
    # 내 팀이 있는 리그를 보여 준다. 리그 이름은 인원이 많은 리그일수록 높은 등급 (화면용)
    idx = next((i for i, lg in enumerate(leagues) if any(t.team_id in my_ids for t in lg)), None)
    league = leagues[idx] if idx is not None else (leagues[0] if leagues else [])
    tier = LEAGUE_TIERS[(len(leagues) - 1 - (idx or 0)) % len(LEAGUE_TIERS)] if leagues else ""
    team_cards = [(t, await team_service.members(session, t.id)) for t in mine]
    now = utcnow()
    races = [
        await _race_card(session, b, user.id)
        for b in await battle_service.battles_of(session, user.id)
        if battle_service.status_at(b, now).value != "finished"
    ]
    return await render(
        request,
        "teams.html",
        user,
        session,
        league=league,
        tier=tier,
        my_ids=my_ids,
        teams=team_cards,
        races=races,
        tab="league",
    )


@router.post("/teams")
async def create_team(
    request: Request,
    name: str = Form(...),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    team = await team_service.create_team(session, user, name)
    return redirect(f"/teams/{team.id}")


@router.post("/teams/join")
async def join_team(
    request: Request,
    code: str = Form(...),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    team = await team_service.join_team(session, code.strip(), user)
    return redirect(f"/teams/{team.id}")


@router.get("/teams/{team_id}")
async def team_page(
    request: Request,
    team_id: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "팀을 찾을 수 없어요.")
    members = await team_service.members(session, team.id)
    is_member = any(m.id == user.id for m in members)
    rivals = list(await session.scalars(select(Team).where(Team.id != team.id).order_by(Team.id)))
    books = [b for _, b in await lib.list_entries(session, user.id)]
    battles = [
        b for b in await battle_service.battles_of(session, user.id) if team.id in (b.team_a_id, b.team_b_id)
    ]
    league = await team_service.league_of(session, team.id)
    return await render(
        request,
        "team.html",
        user,
        session,
        team=team,
        members=members,
        is_member=is_member,
        rivals=rivals,
        books=books,
        battles=battles,
        league=league,
        today=utcnow().astimezone(KST).date(),
    )


@router.post("/teams/{team_id}/leave")
async def leave_team(
    request: Request,
    team_id: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(404)
    await team_service.leave_team(session, team, user)
    return redirect("/teams")


@router.post("/battles")
async def create_battle(
    request: Request,
    type: BattleType = Form(...),
    book_id: int = Form(...),
    team_a_id: int = Form(...),
    team_b_id: int = Form(...),
    days: int = Form(7),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    book = await session.get(Book, book_id)
    a, b = await session.get(Team, team_a_id), await session.get(Team, team_b_id)
    if not (book and a and b):
        raise HTTPException(404)
    now = utcnow()
    battle = await battle_service.create_battle(
        session, user, type, book, a, b, now, now + timedelta(days=days)
    )
    return redirect(f"/battles/{battle.id}")


@router.get("/battles/{battle_id}")
async def battle_page(
    request: Request,
    battle_id: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    battle = await session.get(Battle, battle_id)
    if battle is None or not await battle_service.is_participant(session, battle, user.id):
        raise HTTPException(404, "배틀을 찾을 수 없어요.")
    await battle_service.settle(session, battle)
    a, b = await battle_service.sides(session, battle)
    book = await session.get(Book, battle.book_id)
    hs = await battle_service.highlights(session, battle, user.id)
    status = battle_service.status_at(battle, utcnow())
    win = await battle_service.winner(session, battle) if status.value == "finished" else None
    votes_used = sum(1 for h in hs if h.voted_by_me)
    return await render(
        request,
        "battle.html",
        user,
        session,
        battle=battle,
        a=a,
        b=b,
        book=book,
        highlights=hs,
        status=status,
        winner=win,
        votes_left=battle_service.VOTES_PER_USER - votes_used,
    )


@router.post("/battles/{battle_id}/highlights")
async def add_highlight(
    request: Request,
    battle_id: int,
    chunk_index: int = Form(...),
    quote_text: str = Form(...),
    comment: str = Form(""),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    battle = await session.get(Battle, battle_id)
    if battle is None:
        raise HTTPException(404)
    await battle_service.add_highlight(session, battle, user, chunk_index, quote_text, comment or None)
    flash(request, "밑줄을 올렸어요.")
    return redirect(_back(request, f"/battles/{battle_id}"))


@router.post("/battles/{battle_id}/highlights/{highlight_id}/vote")
async def vote(
    request: Request,
    battle_id: int,
    highlight_id: int,
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    battle = await session.get(Battle, battle_id)
    if battle is None:
        raise HTTPException(404)
    await battle_service.vote(session, battle, highlight_id, user)
    return redirect(f"/battles/{battle_id}")


# ── 내 정보 · 알림 ─────────────────────────────────────────


@router.get("/me")
async def me_page(
    request: Request, user: User = Depends(need_user), session: AsyncSession = Depends(get_session)
):
    now = utcnow()
    challenges = [
        (c, await point_service.progress_of(session, user.id, c, now), point_service.goal_of(c))
        for c in point_service.CHALLENGES
    ]
    inbox = await noti.inbox(session, user.id, now)
    await noti.mark_all_read(session, user.id, now)
    return await render(
        request,
        "me.html",
        user,
        session,
        balance=await point_service.balance(session, user.id),
        history=await point_service.history(session, user.id),
        challenges=challenges,
        inbox=inbox,
        teams=await team_service.teams_of(session, user.id),
    )


@router.post("/me/settings")
async def update_settings(
    request: Request,
    spoiler_guard: str = Form("off"),
    user: User = Depends(need_user),
    session: AsyncSession = Depends(get_session),
):
    user.spoiler_guard = spoiler_guard == "on"
    await session.commit()
    flash(
        request,
        "스포일러 가드를 " + ("켰어요." if user.spoiler_guard else "껐어요. 앞선 반응이 모두 보여요."),
    )
    return redirect("/me")
