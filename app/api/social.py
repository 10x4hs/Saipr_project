from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import check_csrf, require_api_user, user_of_session
from app.db.session import get_session
from app.models import Book, Room, User
from app.realtime import broker
from app.services import books as book_service
from app.services import races as race_service
from app.services import social


def avatar_url(user: User) -> str | None:
    from app.web import avatar_url as _url  # 화면과 같은 주소 규칙

    return _url(user)


router = APIRouter(prefix="/api/v1", tags=["social"])


async def _readable(session: AsyncSession, book_id: int, user: User) -> Book:
    book = await session.get(Book, book_id)
    if book is None or not book_service.can_read(book, user.id):
        raise HTTPException(404, "book not found")
    return book


class ReactionIn(BaseModel):
    chunk_index: int
    anchor: int = 0
    emoji: str | None = None
    comment: str | None = None


@router.get("/books/{book_id}/reactions")
async def list_reactions(
    book_id: int,
    chunk: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_api_user),
) -> dict:
    book = await _readable(session, book_id, user)
    return await social.reactions_for(session, user, book, chunk)


@router.post("/books/{book_id}/reactions", status_code=201)
async def post_reaction(
    book_id: int,
    body: ReactionIn,
    request: Request,
    x_csrf_token: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_api_user),
) -> dict:
    check_csrf(request, x_csrf_token)
    book = await _readable(session, book_id, user)
    try:
        r = await social.add_reaction(
            session, user, book, body.chunk_index, body.anchor, body.emoji, body.comment
        )
    except social.ReactionError as e:
        raise HTTPException(422, str(e)) from e
    others = await social.circle(session, user.id, book.id) - {user.id}
    # 본문은 싣지 않는다: 받는 쪽이 자기 스포일러 가드로 다시 읽는다
    await broker.publish(
        book.id,
        others,
        {
            "type": "reaction.added",
            "chunk": r.chunk_index,
            "user_id": user.id,
            "nickname": user.nickname,
            "avatar": social.avatar_path(user.id, user.avatar),
        },
    )
    return social._out(r, user.nickname, user.id)


@router.delete("/books/{book_id}/reactions/{reaction_id}", status_code=204)
async def delete_reaction(
    book_id: int,
    reaction_id: int,
    request: Request,
    x_csrf_token: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_api_user),
) -> None:
    check_csrf(request, x_csrf_token)
    book = await _readable(session, book_id, user)
    removed = await social.delete_reaction(session, user, book, reaction_id)
    if removed is None:
        raise HTTPException(404, "reaction not found")  # 남의 반응도 같은 응답 — 있는지조차 알리지 않는다
    others = await social.circle(session, user.id, book.id) - {user.id}
    await broker.publish(book.id, others, {"type": "reaction.removed", "chunk": removed.chunk_index})


@router.get("/books/{book_id}/social")
async def book_social(
    book_id: int, session: AsyncSession = Depends(get_session), user: User = Depends(require_api_user)
) -> dict:
    book = await _readable(session, book_id, user)
    return {
        "friends": [f.__dict__ for f in await social.friends(session, user, book)],
        "sealed_ahead": await social.sealed_ahead(session, user, book),
        "emojis": social.EMOJIS,
    }


@router.get("/races/{room_id}/standings")
async def standings(
    room_id: int, session: AsyncSession = Depends(get_session), user: User = Depends(require_api_user)
) -> dict:
    room = await _race_of(session, room_id, user)
    board = await race_service.standings(session, room, user.id)
    return {
        "book_id": room.book_id,
        "over": race_service.is_over(room),
        "board": [
            {
                "user_id": s.user.id,
                "nickname": s.user.nickname,
                "avatar": avatar_url(s.user),
                "pages": s.pages,
                "pct": s.pct,
                "me": s.is_me,
            }
            for s in board
        ],
    }


async def _race_of(session: AsyncSession, room_id: int, user: User) -> Room:
    room = await session.get(Room, room_id)
    if room is None or not await race_service.is_member(session, room, user.id):
        raise HTTPException(404, "race not found")  # 남의 방은 있는지조차 알리지 않는다
    return room


def _present_out(p: race_service.Present) -> dict:
    return {
        "user_id": p.user.id,
        "nickname": p.user.nickname,
        "avatar": avatar_url(p.user),
        "chunk": p.chunk_index,
        "room_id": p.room_id,
    }


class PresenceIn(BaseModel):
    chunk_index: int


@router.put("/books/{book_id}/presence")
async def book_presence(
    book_id: int,
    body: PresenceIn,
    request: Request,
    x_csrf_token: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_api_user),
) -> dict:
    """리더의 심장박동 겸 조회 — 내 쪽을 기록하고, 이 책을 지금 펼친 친구들이 어디를 읽는지 돌려준다.

    친구 = 같은 대결방(이 책)뿐 아니라 어떤 방·팀이든 함께 쓰는 사람. 60초 소식이 없으면 뺀다.
    """
    check_csrf(request, x_csrf_token)
    book = await _readable(session, book_id, user)
    rooms = await race_service.heartbeat(session, user, book, body.chunk_index)  # 대결방 화면용
    await book_service.touch_presence(session, user.id, book, body.chunk_index)
    friends = await book_service.reading_now(session, user.id, book)
    return {
        "rooms": [{"id": r.id, "name": r.name} for r in rooms],
        "friends": [
            {
                "user_id": f.user.id,
                "nickname": f.user.nickname,
                "avatar": avatar_url(f.user),
                "chunk": f.chunk_index,
                "verified_chunk": f.verified_chunk,
            }
            for f in friends
        ],
        "ttl": int(book_service.PRESENCE_TTL.total_seconds()),
    }


@router.get("/races/{room_id}/presence")
async def race_presence(
    room_id: int, session: AsyncSession = Depends(get_session), user: User = Depends(require_api_user)
) -> dict:
    room = await _race_of(session, room_id, user)
    return {"present": [_present_out(p) for p in await race_service.present(session, [room.id])]}


class QuoteIn(BaseModel):
    chunk_index: int
    text: str


@router.get("/races/{room_id}/quotes")
async def list_quotes(
    room_id: int, session: AsyncSession = Depends(get_session), user: User = Depends(require_api_user)
) -> dict:
    room = await _race_of(session, room_id, user)
    return {"items": await race_service.quotes(session, room, user.id)}


@router.post("/races/{room_id}/quotes", status_code=201)
async def post_quote(
    room_id: int,
    body: QuoteIn,
    request: Request,
    x_csrf_token: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_api_user),
) -> dict:
    check_csrf(request, x_csrf_token)
    room = await _race_of(session, room_id, user)
    try:
        q = await race_service.add_quote(session, room, user, body.chunk_index, body.text)
    except race_service.QuoteError as e:
        raise HTTPException(422, str(e)) from e
    return {"id": q.id, "chunk": q.chunk_index, "text": q.body}


@router.websocket("/ws/books/{book_id}")
async def book_socket(
    websocket: WebSocket, book_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    """같은 책을 읽는 친구의 진행·반응 소식을 받는 연결 (로그인 세션 필요)."""
    # HTTP와 같은 규칙: 30분 유휴 만료와 로그아웃 무효화를 함께 검사
    user = await user_of_session(websocket, session) if "session" in websocket.scope else None
    book = await session.get(Book, book_id)
    if user is None or book is None or not book_service.can_read(book, user.id):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    broker.join(book_id, user.id, websocket)
    try:
        while True:
            await websocket.receive_text()  # 클라이언트는 연결 유지용 핑만 보낸다
    except WebSocketDisconnect:
        pass
    finally:
        broker.leave(book_id, user.id, websocket)
