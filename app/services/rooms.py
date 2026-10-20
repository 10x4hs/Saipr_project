"""읽기방 · 초대 코드 (PRD ROOM-01) · 진행률 브로드캐스트 (ROOM-02)."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import aware, utcnow
from app.db.session import defer_publish
from app.models import Book, LibraryEntry, Room, RoomMember, RoomMode, Shelf, User
from app.realtime.broker import broker, room_channel
from app.services import activity, library
from app.services.notifications import notify

MAX_MEMBERS = 8
INVITE_TTL = timedelta(days=7)


class RoomError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(slots=True)
class MemberView:
    user_id: int
    nickname: str
    is_owner: bool
    verified_chunk: int
    progress_pct: int
    joined_at: datetime


def new_invite_code() -> str:
    return secrets.token_urlsafe(6)  # 8자리


async def create_room(
    session: AsyncSession,
    owner: User,
    book: Book,
    name: str,
    mode: RoomMode = RoomMode.ASYNC,
    ends_at: datetime | None = None,
    now: datetime | None = None,
) -> Room:
    now = now or utcnow()
    name = name.strip()
    if not name or len(name) > 80:
        raise RoomError("방 이름은 1~80자로 정해 주세요.")
    room = Room(
        book_id=book.id,
        owner_id=owner.id,
        name=name,
        mode=mode,
        invite_code=new_invite_code(),
        invite_expires_at=now + INVITE_TTL,
        ends_at=aware(ends_at) if ends_at else None,
        created_at=now,
    )
    session.add(room)
    await session.flush()
    session.add(RoomMember(room_id=room.id, user_id=owner.id, joined_at=now))
    await library.ensure_entry(session, owner.id, book.id, Shelf.READING)
    await activity.joined_room(session, owner.id, book.id, room.id, room.name, now)
    await session.commit()
    return room


async def regenerate_invite(
    session: AsyncSession, room: Room, user: User, now: datetime | None = None
) -> Room:
    if room.owner_id != user.id:
        raise RoomError("방장만 초대 링크를 다시 만들 수 있어요.", 403)
    now = now or utcnow()
    for _ in range(3):
        room.invite_code = new_invite_code()
        room.invite_expires_at = now + INVITE_TTL
        try:
            await session.commit()
            return room
        except IntegrityError:
            await session.rollback()
    raise RoomError("초대 코드를 만들지 못했어요. 다시 시도해 주세요.", 500)


async def by_code(session: AsyncSession, code: str) -> Room | None:
    return await session.scalar(select(Room).where(Room.invite_code == code))


async def is_member(session: AsyncSession, room_id: int, user_id: int) -> bool:
    return bool(
        await session.scalar(
            select(RoomMember.user_id).where(RoomMember.room_id == room_id, RoomMember.user_id == user_id)
        )
    )


async def member_ids(session: AsyncSession, room_id: int) -> list[int]:
    return list(await session.scalars(select(RoomMember.user_id).where(RoomMember.room_id == room_id)))


async def members(session: AsyncSession, room: Room) -> list[MemberView]:
    rows = await session.execute(
        select(User, RoomMember.joined_at, LibraryEntry)
        .join(RoomMember, RoomMember.user_id == User.id)
        .outerjoin(LibraryEntry, (LibraryEntry.user_id == User.id) & (LibraryEntry.book_id == room.book_id))
        .where(RoomMember.room_id == room.id)
        .order_by(RoomMember.joined_at, User.id)
    )
    return [
        MemberView(
            user_id=u.id,
            nickname=u.nickname,
            is_owner=u.id == room.owner_id,
            verified_chunk=e.verified_chunk if e else -1,
            progress_pct=e.progress_pct if e else 0,
            joined_at=joined,
        )
        for u, joined, e in rows.all()
    ]


async def join(session: AsyncSession, code: str, user: User, now: datetime | None = None) -> Room:
    now = now or utcnow()
    room = await by_code(session, code)
    if room is None:
        raise RoomError("초대 링크를 찾을 수 없어요.", 404)
    if await is_member(session, room.id, user.id):
        return room
    if room.archived:
        raise RoomError("보관된 방이에요.", 410)
    if room.invite_expires_at and aware(room.invite_expires_at) < now:
        raise RoomError("초대 링크가 만료됐어요. 방장에게 새 링크를 받아 주세요.", 410)
    count = await session.scalar(
        select(func.count()).select_from(RoomMember).where(RoomMember.room_id == room.id)
    )
    if (count or 0) >= MAX_MEMBERS:
        raise RoomError(f"방이 가득 찼어요 (최대 {MAX_MEMBERS}명).", 409)
    session.add(RoomMember(room_id=room.id, user_id=user.id, joined_at=now))
    entry = await library.ensure_entry(session, user.id, room.book_id, Shelf.READING)
    defer_publish(
        session,
        room_channel(room.id),
        "member.joined",
        {
            "user_id": user.id,
            "nickname": user.nickname,
            "progress_pct": entry.progress_pct,
            "verified_chunk": entry.verified_chunk,
        },
    )
    await activity.joined_room(session, user.id, room.book_id, room.id, room.name, now)
    await notify(
        session,
        room.owner_id,
        "room_joined",
        f"{user.nickname}님이 「{room.name}」에 들어왔어요.",
        f"/rooms/{room.id}",
        now,
    )
    try:
        await session.commit()
    except IntegrityError:
        # 같은 사람이 동시에 두 번 눌렀을 때
        await session.rollback()
    return room


async def leave(session: AsyncSession, room: Room, user: User) -> None:
    """방장이 나가면 가장 먼저 들어온 멤버에게 위임, 아무도 없으면 보관 (PRD EXC-06)."""
    m = await session.get(RoomMember, (room.id, user.id))
    if m is None:
        raise RoomError("이 방의 멤버가 아니에요.", 404)
    await session.delete(m)
    await session.flush()
    # 열려 있던 내 소켓도 이 이벤트를 받고 닫힌다 (api/ws.py)
    defer_publish(
        session, room_channel(room.id), "member.left", {"user_id": user.id, "nickname": user.nickname}
    )
    if room.owner_id == user.id:
        heir = await session.scalar(
            select(RoomMember.user_id)
            .where(RoomMember.room_id == room.id)
            .order_by(RoomMember.joined_at, RoomMember.user_id)
            .limit(1)
        )
        if heir is None:
            room.archived = True
        else:
            room.owner_id = heir
            await notify(
                session, heir, "room_owner", f"「{room.name}」의 방장이 되었어요.", f"/rooms/{room.id}"
            )
    await session.commit()


async def rooms_of(session: AsyncSession, user_id: int) -> list[tuple[Room, Book]]:
    rows = await session.execute(
        select(Room, Book)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .join(Book, Book.id == Room.book_id)
        .where(RoomMember.user_id == user_id, Room.archived.is_(False))
        .order_by(Room.created_at.desc())
    )
    return [(r, b) for r, b in rows.all()]


async def broadcast_progress(
    session: AsyncSession,
    user: User,
    book: Book,
    entry: LibraryEntry,
    before_chunk: int,
    new_chunks: int = 0,
) -> None:
    """내 진행률이 오르면 같은 책 방마다 progress.updated를 보내고, 내가 앞지른 친구에게 알린다."""
    room_rows = await session.execute(
        select(Room)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .where(RoomMember.user_id == user.id, Room.book_id == book.id, Room.archived.is_(False))
    )
    overtaken: set[int] = set()
    for (room,) in room_rows.all():
        defer_publish(
            session,
            room_channel(room.id),
            "progress.updated",
            {
                "user_id": user.id,
                "nickname": user.nickname,
                "verified_chunk": entry.verified_chunk,
                "progress_pct": entry.progress_pct,
                "new_chunks": new_chunks,
            },
        )
        for m in await members(session, room):
            if m.user_id != user.id and before_chunk <= m.verified_chunk < entry.verified_chunk:
                overtaken.add(m.user_id)
    for uid in overtaken:
        await notify(
            session,
            uid,
            "overtaken",
            f"{user.nickname}님이 「{book.title}」에서 나를 앞질렀어요!",
            f"/books/{book.id}/read",
        )


def publish_presence(room_id: int, user: User, chunk_index: int) -> None:
    """sync 모드 프레즌스. DB를 거치지 않으므로 바로 보낸다."""
    broker.publish(
        room_channel(room_id),
        "presence.changed",
        {"user_id": user.id, "nickname": user.nickname, "chunk_index": chunk_index},
    )
