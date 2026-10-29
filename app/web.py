"""웹 앱 화면 — 소개 · 가입/로그인 · 홈 · 탐색 · 서재 · 검색 · 올리기 · 내 정보 · 리더.

서버 렌더링(Jinja2)이 기본이고, 리더만 작은 JS가 붙는다.
"""

import datetime as dt
import hashlib
import json
import random
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app.api.deps import get_sources
from app.core import appearance
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models import Book, LibraryEntry, Room, Shelf, User
from app.services import books as book_service
from app.services import races as race_service
from app.services.search import FULLTEXT_SOURCES, search_all
from app.services.uploads import parse_upload
from app.sources.base import BookSource, SourceError

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# 서가 카탈로그 — scripts/build_catalog.py로 만든다 (퍼블릭 도메인 확인된 작품만)
DATA = Path(__file__).parent / "data"
STATIC = Path(__file__).parent / "static"


def _load_catalog() -> list[dict]:
    """같은 작품이 여러 번(판본·문서명 차이) 실려 있으면 하나만 남기고, 표지 파일이 없는 환경(배포)에서는
    원본 표지 주소를 쓴다."""
    seen, out = set(), []
    for b in json.loads((DATA / "catalog.json").read_text()):
        key = (b["title"].strip().lower(), (b.get("author") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        if b.get("cover") and not (STATIC / b["cover"].removeprefix("/static/")).exists():
            b["cover"] = b.get("cover_src")
        out.append(b)
    return out


CATALOG: list[dict] = _load_catalog()
# 저작권이 살아 있는 유명 도서 — 본문 없이 정보·표지와 알라딘 전자책 구매 링크만 (scripts/build_store.py)
STORE: list[dict] = json.loads((DATA / "store.json").read_text())
STORE_INDEX = {b["id"]: b for b in STORE}
# 책 소개 유튜브 영상 — scripts/build_videos.py ("store:<알라딘 id>" 또는 "<source>:<id>" → 영상 목록)
VIDEOS: dict[str, list[dict]] = (
    json.loads((DATA / "videos.json").read_text()) if (DATA / "videos.json").exists() else {}
)
GENRE_ORDER = [
    "단편소설", "장편소설", "중편소설", "고전소설", "신소설", "판소리", "시", "시집", "희곡", "동화", "수필",
    "세계 고전", "세계 · 추리", "세계 · SF", "세계 · 판타지", "세계 · 동화", "세계 · 모험", "세계 · 공포",
    "세계 · 로맨스", "세계 · 시", "세계 · 희곡", "세계 · 철학", "세계 · 어린이", "세계 · 역사",
]  # fmt: skip
SHELVES = {g: [b for b in CATALOG if b["genre"] == g] for g in GENRE_ORDER}
SHELVES = {g: books for g, books in SHELVES.items() if books}
CATALOG_INDEX = {(b["source"], b["id"]): b for b in CATALOG}
POPULAR_ORDER = [tuple(k) for k in json.loads((DATA / "popular.json").read_text())["order"]]

COVER_PALETTES = 8


def cover(title: str, author: str | None = None) -> dict:
    """표지가 없는 고전에 쓸 결정적 표지 — 제목 해시로 색과 무늬를 고른다."""
    h = int(hashlib.sha1(f"{title}|{author or ''}".encode()).hexdigest(), 16)
    return {"palette": h % COVER_PALETTES, "pattern": (h >> 8) % 4}


def cover_of(book: Book) -> str | None:
    """책의 실제 표지: 올릴 때 고른 서점 표지 → 카탈로그 표지 순."""
    if book.cover_url:
        return book.cover_url
    meta = CATALOG_INDEX.get((book.source, book.external_id))
    return meta.get("cover") if meta else None


templates.env.globals["cover"] = cover
templates.env.globals["cover_of"] = cover_of
templates.env.globals["APPEARANCE"] = appearance


def _render(request: Request, name: str, user: User | None, **ctx) -> HTMLResponse:
    look = appearance.resolve(user.settings if user else None)
    ctx |= {"user": user, "csrf": auth.csrf_token(request), "path": request.url.path, "look": look}
    return templates.TemplateResponse(request, name, ctx)


def _safe_next(target: str | None) -> str:
    """로그인 뒤 돌아갈 곳 — 이 사이트 안의 경로만.

    `//evil.com`과 `/\\evil.com`(브라우저가 \\를 /로 바꾼다)은 다른 사이트로 가므로 막는다.
    """
    if not target or not target.startswith("/") or "\\" in target or target.startswith("//"):
        return "/"
    parts = urlsplit(target)
    return target if not parts.scheme and not parts.netloc else "/"


def _daily_picks(n: int) -> list[dict]:
    rng = random.Random(dt.date.today().toordinal())
    with_cover = [b for b in CATALOG if b.get("cover")] or CATALOG
    return rng.sample(with_cover, min(n, len(with_cover)))


async def popular(session: AsyncSession, n: int = 20) -> list[dict]:
    """유명 고전 순서에 앱 안 독자 수를 더한 인기 순위."""
    rows = await session.execute(
        select(Book.source, Book.external_id, func.count(LibraryEntry.id))
        .join(LibraryEntry, LibraryEntry.book_id == Book.id)
        .where(Book.owner_id.is_(None))
        .group_by(Book.source, Book.external_id)
    )
    readers = {(src, ext): cnt for src, ext, cnt in rows.all()}
    base = len(POPULAR_ORDER)
    score = {key: base - i for i, key in enumerate(POPULAR_ORDER)}
    for key, cnt in readers.items():
        score[key] = score.get(key, 0) + cnt * 3
    ranked = sorted((k for k in score if k in CATALOG_INDEX), key=lambda k: -score[k])[:n]
    return [CATALOG_INDEX[k] | {"rank": i + 1, "readers": readers.get(k, 0)} for i, k in enumerate(ranked)]


def _fill(ranked: list[dict], n: int) -> list[dict]:
    """인기 순위 뒤를 오늘의 추천으로 채워 드럼 한 바퀴를 꽉 채운다."""
    seen = {(b["source"], b["id"]) for b in ranked}
    extra = [b for b in _daily_picks(n * 2) if (b["source"], b["id"]) not in seen]
    return (ranked + extra)[:n]


# --- 소개 · 가입 · 로그인 ---


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(auth.current_user),
) -> HTMLResponse:
    if user is None:
        return _render(request, "landing.html", None, picks=(await popular(session, 9)), total=len(CATALOG))
    library = await book_service.library_of(session, user.id)
    reading = [(e, b) for e, b in library if e.shelf == Shelf.READING]
    return _render(
        request,
        "home.html",
        user,
        current=reading[0] if reading else None,
        reading=reading[1:6],
        picks=_daily_picks(10),
        marquee=_daily_picks(16),
        popular=(top := await popular(session, 30)),
        drum=[b | {"store": True} for b in STORE[:14]] + _fill(top, 30),
        store=STORE,
        shelves={g: books[:14] for g, books in SHELVES.items()},
    )


@router.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request, user: User | None = Depends(auth.current_user)) -> HTMLResponse:
    if user:
        return RedirectResponse("/", status_code=303)
    return _render(request, "signup.html", None, form=None)


@router.post("/signup", response_class=HTMLResponse, response_model=None)
async def signup(
    request: Request,
    nickname: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    csrf: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    auth.check_csrf(request, csrf)
    form = auth.SignupForm(nickname, email, password, password_confirm)
    if form.validate():
        user = await auth.create_user(session, form)
        if user is not None:
            auth.login(request, user)
            return RedirectResponse("/", status_code=303)
        form.errors["email"] = "이미 가입된 이메일이에요"
    # 비밀번호는 다시 채워 보내지 않는다
    return _render(request, "signup.html", None, form=form)


@router.get("/login", response_class=HTMLResponse)
async def login_form(
    request: Request, next: str | None = None, user: User | None = Depends(auth.current_user)
) -> HTMLResponse:
    if user:
        return RedirectResponse(_safe_next(next), status_code=303)
    return _render(request, "login.html", None, email="", error=None, next=_safe_next(next))


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    csrf: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    auth.check_csrf(request, csrf)
    user = await auth.authenticate(session, email, password)
    if user is None:
        return _render(
            request,
            "login.html",
            None,
            email=auth.normalize_email(email),
            error="이메일 또는 비밀번호가 맞지 않아요",
            next=_safe_next(next),
        )
    auth.login(request, user)
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout")
async def logout(
    request: Request, csrf: str = Form(""), session: AsyncSession = Depends(get_session)
) -> RedirectResponse:
    auth.check_csrf(request, csrf)
    await auth.logout(request, session)
    return RedirectResponse("/", status_code=303)


# --- 앱 ---


@router.get("/discover", response_class=HTMLResponse)
async def discover(
    request: Request, g: str | None = None, user: User = Depends(auth.require_user)
) -> HTMLResponse:
    if g == "서점":
        return _render(
            request,
            "discover.html",
            user,
            genres=SHELVES,
            genre="서점",
            books=[],
            store=STORE,
            total=len(CATALOG),
        )
    genre = g if g in SHELVES else None
    books = SHELVES[genre] if genre else CATALOG
    return _render(
        request,
        "discover.html",
        user,
        genres=SHELVES,
        genre=genre,
        books=books,
        store=STORE,
        total=len(CATALOG),
    )


@router.get("/store/{item_id}", response_class=HTMLResponse)
async def store_item(request: Request, item_id: str, user: User = Depends(auth.require_user)) -> HTMLResponse:
    book = STORE_INDEX.get(item_id)
    if book is None:
        raise HTTPException(404, "책을 찾을 수 없어요")
    return _render(request, "store.html", user, book=book, videos=VIDEOS.get(f"store:{item_id}", []))


@router.get("/shelf/{genre}")
async def shelf(genre: str) -> RedirectResponse:
    if genre not in SHELVES:
        raise HTTPException(404, "서가를 찾을 수 없어요")
    return RedirectResponse(f"/discover?g={genre}", status_code=301)


@router.get("/library", response_class=HTMLResponse)
async def library(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> HTMLResponse:
    entries = await book_service.library_of(session, user.id)
    tabs = {
        "reading": [x for x in entries if x[0].shelf == Shelf.READING],
        "done": [x for x in entries if x[0].shelf == Shelf.DONE],
        "mine": [x for x in entries if x[1].owner_id == user.id],
    }
    uploaded = await book_service.uploads_of(session, user.id)
    return _render(request, "library.html", user, tabs=tabs, uploaded=uploaded)


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query("", max_length=100),
    sources: dict[str, BookSource] = Depends(get_sources),
    settings: Settings = Depends(get_settings),
    user: User = Depends(auth.require_user),
) -> HTMLResponse:
    readable, others, errors = [], [], {}
    term = q.strip()
    in_catalog = [b for b in CATALOG if term and (term in b["title"] or term in (b["author"] or ""))]
    if term:
        result = await search_all(list(sources.values()), term, 20, settings.http_timeout_seconds)
        errors = result.errors
        known = {(b["source"], b["id"]) for b in in_catalog}
        for h in result.hits:
            if (h.meta.source, h.meta.external_id) in known:
                continue
            (readable if h.meta.has_fulltext else others).append(h.meta)
    return _render(
        request,
        "search.html",
        user,
        q=q,
        in_catalog=in_catalog[:30],
        readable=readable,
        others=others,
        errors=errors,
    )


@router.get("/upload", response_class=HTMLResponse)
async def upload_form(
    request: Request, store: str | None = None, user: User = Depends(auth.require_user)
) -> HTMLResponse:
    return _render(
        request,
        "upload.html",
        user,
        error=None,
        for_book=STORE_INDEX.get(store or ""),
        max_mb=get_settings().max_upload_mb,
    )


@router.post("/upload", response_class=HTMLResponse, response_model=None)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    csrf: str = Form(""),
    store: str = Form(""),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> HTMLResponse | RedirectResponse:
    auth.check_csrf(request, csrf)
    for_book = STORE_INDEX.get(store)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    try:
        parsed = parse_upload(file.filename or "untitled.txt", data, limit)
    except SourceError as e:
        resp = _render(
            request, "upload.html", user, error=str(e), for_book=for_book, max_mb=get_settings().max_upload_mb
        )
        resp.status_code = 422
        return resp
    book = await book_service.save_upload(session, parsed, user.id)
    if for_book and not book.cover_url:  # 서점에서 고른 책이면 그 표지를 붙인다
        book.cover_url = for_book.get("cover")
        await session.commit()
    return RedirectResponse(f"/books/{book.id}", status_code=303)


@router.get("/me", response_class=HTMLResponse)
async def me(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> HTMLResponse:
    entries = await book_service.library_of(session, user.id)
    stats = {
        "reading": sum(e.shelf == Shelf.READING for e, _ in entries),
        "done": sum(e.shelf == Shelf.DONE for e, _ in entries),
        "pages": sum(e.verified_chunk + 1 for e, _ in entries),
    }
    return _render(
        request,
        "me.html",
        user,
        stats=stats,
        error=request.query_params.get("error"),
        saved=bool(request.query_params.get("saved")),
    )


@router.get("/open/{source}/{external_id:path}")
async def open_book(
    source: str,
    external_id: str,
    sources: dict[str, BookSource] = Depends(get_sources),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> RedirectResponse:
    """퍼블릭 도메인 전문을 가져와(이미 있으면 캐시) 서재에 꽂고 리더로 보낸다."""
    src = sources.get(source)
    if src is None or source not in FULLTEXT_SOURCES:
        raise HTTPException(400, "이 책은 앱에서 본문을 제공하지 않아요")
    try:
        book = await book_service.import_book(session, src, external_id)
    except SourceError as e:
        raise HTTPException(422, f"본문을 가져오지 못했어요: {e}") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"{source} 응답이 없어요 ({type(e).__name__})") from e
    meta = CATALOG_INDEX.get((source, external_id))
    if meta and not book.author and meta["author"]:
        book.author = meta["author"]  # 위키문헌 API는 저자를 주지 않아 카탈로그로 채운다
        await session.commit()
    return RedirectResponse(f"/books/{book.id}", status_code=303)


@router.get("/books/{book_id}", response_class=HTMLResponse)
async def reader(
    request: Request,
    book_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> HTMLResponse:
    book = await session.get(Book, book_id)
    if book is None or not book_service.can_read(book, user.id):
        raise HTTPException(404, "책을 찾을 수 없어요")
    entry = await book_service.shelve(session, user.id, book.id)
    videos = VIDEOS.get(f"{book.source}:{book.external_id}", [])
    return _render(request, "reader.html", user, book=book, entry=entry, videos=videos)


# --- 친구 대결 ---


@router.get("/races", response_class=HTMLResponse)
async def races(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> HTMLResponse:
    mine = await race_service.races_of(session, user.id)
    reading = [b for e, b in await book_service.library_of(session, user.id) if e.shelf == Shelf.READING]
    return _render(
        request,
        "races.html",
        user,
        races=[(r, b, race_service.is_over(r)) for r, b in mine],
        reading=reading,
        popular=await popular(session, 12),
        durations=race_service.DURATIONS,
        error=request.query_params.get("error"),
    )


@router.post("/races")
async def create_race(
    request: Request,
    book_id: int = Form(...),
    days: int = Form(7),
    csrf: str = Form(""),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> RedirectResponse:
    auth.check_csrf(request, csrf)
    book = await session.get(Book, book_id)
    if book is None or not book_service.can_read(book, user.id) or book.owner_id is not None:
        raise HTTPException(400, "대결은 서가에 있는 책으로만 열 수 있어요")
    room = await race_service.create_race(session, user, book, days)
    return RedirectResponse(f"/races/{room.id}", status_code=303)


@router.post("/races/start/{source}/{external_id:path}")
async def create_race_from_catalog(
    request: Request,
    source: str,
    external_id: str,
    days: int = Form(7),
    csrf: str = Form(""),
    sources: dict[str, BookSource] = Depends(get_sources),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> RedirectResponse:
    """인기 고전을 골라 바로 대결 열기 — 아직 안 가져온 책이면 가져온다."""
    auth.check_csrf(request, csrf)
    src = sources.get(source)
    if src is None or source not in FULLTEXT_SOURCES:
        raise HTTPException(400, "이 책으로는 대결을 열 수 없어요")
    try:
        book = await book_service.import_book(session, src, external_id)
    except (SourceError, httpx.HTTPError) as e:
        raise HTTPException(502, f"책을 가져오지 못했어요 ({type(e).__name__})") from e
    room = await race_service.create_race(session, user, book, days)
    return RedirectResponse(f"/races/{room.id}", status_code=303)


@router.get("/races/{room_id}", response_class=HTMLResponse)
async def race(
    request: Request,
    room_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> HTMLResponse:

    room = await session.get(Room, room_id)
    if room is None or not await race_service.is_member(session, room, user.id):
        raise HTTPException(404, "대결을 찾을 수 없어요")
    book = await session.get(Book, room.book_id)
    board = await race_service.standings(session, room, user.id)
    invite = str(request.base_url).rstrip("/") + f"/join/{room.invite_code}"
    return _render(
        request,
        "race.html",
        user,
        room=room,
        book=book,
        board=board,
        invite=invite,
        over=race_service.is_over(room),
    )


@router.post("/join")
async def join_by_form(code: str = Form("")) -> RedirectResponse:
    return RedirectResponse(f"/join/{race_service.normalize_code(code)}", status_code=303)


@router.get("/join/{code}", response_class=HTMLResponse, response_model=None)
async def join_preview(
    request: Request,
    code: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> HTMLResponse | RedirectResponse:
    room = await race_service.by_code(session, code)
    if room is None:
        return RedirectResponse("/races?error=코드를 찾을 수 없어요", status_code=303)
    if await race_service.is_member(session, room, user.id):
        return RedirectResponse(f"/races/{room.id}", status_code=303)
    book = await session.get(Book, room.book_id)
    owner = await session.get(User, room.owner_id)
    count = await race_service.member_count(session, room)
    return _render(request, "join.html", user, room=room, book=book, owner=owner, count=count)


@router.post("/join/{code}")
async def join(
    request: Request,
    code: str,
    csrf: str = Form(""),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> RedirectResponse:
    auth.check_csrf(request, csrf)
    room = await race_service.by_code(session, code)
    if room is None:
        return RedirectResponse("/races?error=코드를 찾을 수 없어요", status_code=303)
    if reason := await race_service.join(session, room, user):
        return RedirectResponse(f"/races?error={reason}", status_code=303)
    await book_service.shelve(session, user.id, room.book_id)
    return RedirectResponse(f"/races/{room.id}", status_code=303)


# --- 프로필 ---

MAX_AVATAR_BYTES = 300_000


def avatar_url(user: User | None) -> str | None:
    if user is None or not user.avatar:
        return None
    return f"/avatars/{user.id}?v={hashlib.sha1(user.avatar).hexdigest()[:8]}"


templates.env.globals["avatar_url"] = avatar_url


@router.get("/avatars/{user_id}")
async def avatar(
    user_id: int, session: AsyncSession = Depends(get_session), _: User = Depends(auth.require_user)
):
    from fastapi.responses import Response

    u = await session.get(User, user_id)
    if u is None or not u.avatar or not await race_service.shares_room(session, _.id, user_id):
        raise HTTPException(404)  # 본인이나 같은 대결방 사람의 사진만
    return Response(
        u.avatar, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"}
    )


@router.post("/me/profile")
async def update_profile(
    request: Request,
    nickname: str = Form(""),
    photo: UploadFile | None = File(None),
    remove_photo: str = Form(""),
    csrf: str = Form(""),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(auth.require_user),
) -> RedirectResponse:
    auth.check_csrf(request, csrf)
    name = nickname.strip()
    if not 1 <= len(name) <= 40:
        return RedirectResponse("/me?error=이름은 1~40자로 입력해 주세요", status_code=303)
    user.nickname = name
    if remove_photo:
        user.avatar = None
    elif photo is not None and photo.filename:
        data = await photo.read(MAX_AVATAR_BYTES + 1)
        # 브라우저가 줄여 보낸 JPEG만 받는다 (매직 넘버 확인)
        if len(data) > MAX_AVATAR_BYTES or not data.startswith(b"\xff\xd8\xff"):
            return RedirectResponse(
                "/me?error=사진을 읽지 못했어요. 다른 사진으로 해 주세요", status_code=303
            )
        user.avatar = data
    await session.commit()
    return RedirectResponse("/me?saved=1", status_code=303)
