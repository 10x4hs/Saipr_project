from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_book, verify_csrf
from app.db.session import get_session
from app.models import Book, ReactionKind, Room, RoomMode, User
from app.services import reactions as reaction_service
from app.services import rooms as room_service
from app.services.teams import verified_counts

router = APIRouter(prefix="/api/v1", tags=["rooms"], dependencies=[Depends(verify_csrf)])


class RoomIn(BaseModel):
    book_id: int
    name: str = Field(min_length=1, max_length=80)
    mode: RoomMode = RoomMode.ASYNC
    ends_at: datetime | None = None


class MemberOut(BaseModel):
    user_id: int
    nickname: str
    is_owner: bool
    verified_chunk: int
    progress_pct: int


class RoomOut(BaseModel):
    id: int
    name: str
    mode: RoomMode
    book_id: int
    book_title: str
    has_fulltext: bool
    total_chunks: int
    invite_code: str | None
    invite_expires_at: datetime | None
    members: list[MemberOut]


class RaceRowOut(BaseModel):
    user_id: int
    nickname: str
    verified_chunks: int


class ReactionIn(BaseModel):
    chunk_index: int
    anchor: int = 0
    kind: ReactionKind
    body: str = Field(min_length=1, max_length=280)


class ReactionOut(BaseModel):
    id: int
    user_id: int
    nickname: str
    chunk_index: int
    anchor: int
    kind: str
    body: str
    created_at: datetime


class FeedOut(BaseModel):
    position: int
    spoiler_guard: bool
    visible: list[ReactionOut]
    locked: dict[int, int]
    locked_total: int


async def room_out(session: AsyncSession, room: Room, viewer: User | None) -> RoomOut:
    book = await session.get(Book, room.book_id)
    ms = await room_service.members(session, room)
    is_member = viewer is not None and any(m.user_id == viewer.id for m in ms)
    return RoomOut(
        id=room.id,
        name=room.name,
        mode=room.mode,
        book_id=room.book_id,
        book_title=book.title,
        has_fulltext=book.has_fulltext,
        total_chunks=book.total_chunks,
        # 초대 코드는 멤버에게만 보여 준다
        invite_code=room.invite_code if is_member else None,
        invite_expires_at=room.invite_expires_at if is_member else None,
        members=[
            MemberOut(
                user_id=m.user_id,
                nickname=m.nickname,
                is_owner=m.is_owner,
                verified_chunk=m.verified_chunk,
                progress_pct=m.progress_pct,
            )
            for m in ms
        ],
    )


async def member_room(room_id: int, user: User, session: AsyncSession) -> Room:
    room = await session.get(Room, room_id)
    if room is None or not await room_service.is_member(session, room_id, user.id):
        raise HTTPException(404, "방을 찾을 수 없어요.")
    return room


@router.post("/rooms", response_model=RoomOut, status_code=201)
async def create_room(
    body: RoomIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    book = await session.get(Book, body.book_id)
    if book is None:
        raise HTTPException(404, "책을 찾을 수 없어요.")
    room = await room_service.create_room(session, user, book, body.name, body.mode, body.ends_at)
    return await room_out(session, room, user)


@router.get("/rooms", response_model=list[RoomOut])
async def my_rooms(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [await room_out(session, r, user) for r, _ in await room_service.rooms_of(session, user.id)]


@router.get("/rooms/{room_id}", response_model=RoomOut)
async def get_room(
    room_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    return await room_out(session, await member_room(room_id, user, session), user)


@router.get("/invites/{code}", response_model=RoomOut)
async def preview_invite(code: str, session: AsyncSession = Depends(get_session)):
    """비로그인 미리보기: 책·멤버·진행률만 (PRD ROOM-01)."""
    room = await room_service.by_code(session, code)
    if room is None or room.archived:
        raise HTTPException(404, "초대 링크를 찾을 수 없어요.")
    return await room_out(session, room, None)


@router.post("/invites/{code}/join", response_model=RoomOut)
async def join_room(
    code: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    room = await room_service.join(session, code, user)
    return await room_out(session, room, user)


@router.post("/rooms/{room_id}/invite", response_model=RoomOut)
async def regenerate_invite(
    room_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    room = await room_service.regenerate_invite(session, await member_room(room_id, user, session), user)
    return await room_out(session, room, user)


@router.post("/rooms/{room_id}/leave", status_code=204)
async def leave_room(
    room_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    await room_service.leave(session, await member_room(room_id, user, session), user)


@router.get("/rooms/{room_id}/race", response_model=list[RaceRowOut])
async def room_race(
    room_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    """방 안 개인전: 방이 생긴 뒤 이 책에서 검증된 청크 수 순위."""
    room = await member_room(room_id, user, session)
    ms = await room_service.members(session, room)
    counts = await verified_counts(session, [m.user_id for m in ms], room.created_at, book_id=room.book_id)
    rows = [RaceRowOut(user_id=m.user_id, nickname=m.nickname, verified_chunks=counts[m.user_id]) for m in ms]
    return sorted(rows, key=lambda r: (-r.verified_chunks, r.user_id))


@router.post("/books/{book_id}/reactions", response_model=ReactionOut, status_code=201)
async def create_reaction(
    body: ReactionIn,
    book: Book = Depends(get_book),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    r = await reaction_service.create(
        session, user, book, body.chunk_index, body.anchor, body.kind, body.body
    )
    return ReactionOut(
        id=r.id,
        user_id=user.id,
        nickname=user.nickname,
        chunk_index=r.chunk_index,
        anchor=r.anchor,
        kind=r.kind.value,
        body=r.body,
        created_at=r.created_at,
    )


@router.get("/books/{book_id}/reactions", response_model=FeedOut)
async def list_reactions(
    room_id: int | None = None,
    chunk_from: int | None = Query(None, ge=0),
    chunk_to: int | None = Query(None, ge=0),
    book: Book = Depends(get_book),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    room = await session.get(Room, room_id) if room_id is not None else None
    if room_id is not None and room is None:
        raise HTTPException(404, "방을 찾을 수 없어요.")
    f = await reaction_service.feed(session, user, book, room, chunk_from, chunk_to)
    return FeedOut(
        position=f.position,
        spoiler_guard=f.spoiler_guard,
        visible=[ReactionOut(**asdict(v)) for v in f.visible],
        locked=f.locked,
        locked_total=f.locked_total,
    )
