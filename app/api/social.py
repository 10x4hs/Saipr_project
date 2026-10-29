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
        book.id, others, {"type": "reaction.added", "chunk": r.chunk_index, "nickname": user.nickname}
    )
    return social._out(r, user.nickname, user.id)


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
    room = await session.get(Room, room_id)
    if room is None or not await race_service.is_member(session, room, user.id):
        raise HTTPException(404, "race not found")
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
