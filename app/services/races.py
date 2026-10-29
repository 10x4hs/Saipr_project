"""친구 대결(페이지 레이스) — 초대 코드로 같은 책을 함께 읽고, 검증된 쪽 수로 순위를 매긴다.

DB의 rooms / room_members 테이블을 그대로 쓴다. 점수는 체류시간 검증을 통과한 청크 수라서
넘기기만 해서는 올라가지 않는다.
"""

import datetime as dt
import secrets
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, LibraryEntry, Room, RoomMember, User

# 헷갈리는 글자(0/O, 1/I/L)를 뺀 코드 문자
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 6
DURATIONS = (1, 3, 7, 14)
MAX_MEMBERS = 8


@dataclass
class Standing:
    user: User
    pages: int
    pct: int
    is_me: bool


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())[:16]


async def create_race(session: AsyncSession, owner: User, book: Book, days: int) -> Room:
    days = days if days in DURATIONS else 7
    ends = dt.datetime.now(dt.UTC) + dt.timedelta(days=days)
    for _ in range(5):  # 코드가 겹치면 다시 뽑는다
        room = Room(
            book_id=book.id,
            owner_id=owner.id,
            name=f"{book.title} 레이스",
            invite_code=new_code(),
            ends_at=ends,
        )
        session.add(room)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        session.add(RoomMember(room_id=room.id, user_id=owner.id))
        await session.commit()
        return room
    raise RuntimeError("invite code space exhausted")


async def by_code(session: AsyncSession, code: str) -> Room | None:
    return await session.scalar(select(Room).where(Room.invite_code == normalize_code(code)))


async def is_member(session: AsyncSession, room: Room, user_id: int) -> bool:
    return bool(
        await session.scalar(
            select(RoomMember.user_id).where(RoomMember.room_id == room.id, RoomMember.user_id == user_id)
        )
    )


async def member_count(session: AsyncSession, room: Room) -> int:
    return await session.scalar(select(func.count()).where(RoomMember.room_id == room.id)) or 0


async def join(session: AsyncSession, room: Room, user: User) -> str | None:
    """참가시키고 None, 못 하면 이유를 돌려준다."""
    if await is_member(session, room, user.id):
        return None
    if is_over(room):
        return "이미 끝난 대결이에요"
    if await member_count(session, room) >= MAX_MEMBERS:
        return f"정원({MAX_MEMBERS}명)이 다 찼어요"
    session.add(RoomMember(room_id=room.id, user_id=user.id))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
    return None


def is_over(room: Room) -> bool:
    ends = room.ends_at
    if ends is None:
        return False
    if ends.tzinfo is None:  # SQLite는 시간대를 저장하지 않는다
        ends = ends.replace(tzinfo=dt.UTC)
    return dt.datetime.now(dt.UTC) >= ends


async def standings(session: AsyncSession, room: Room, me_id: int) -> list[Standing]:
    book = await session.get(Book, room.book_id)
    rows = await session.execute(
        select(User, LibraryEntry.verified_chunk)
        .join(RoomMember, RoomMember.user_id == User.id)
        .outerjoin(LibraryEntry, (LibraryEntry.user_id == User.id) & (LibraryEntry.book_id == room.book_id))
        .where(RoomMember.room_id == room.id)
    )
    total = max(book.total_chunks if book else 1, 1)
    out = [
        Standing(
            user=u,
            pages=(v + 1) if v is not None else 0,
            pct=round(((v + 1) if v is not None else 0) / total * 100),
            is_me=u.id == me_id,
        )
        for u, v in rows.all()
    ]
    return sorted(out, key=lambda s: (-s.pages, s.user.id))


async def races_of(session: AsyncSession, user_id: int) -> list[tuple[Room, Book]]:
    rows = await session.execute(
        select(Room, Book)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .join(Book, Book.id == Room.book_id)
        .where(RoomMember.user_id == user_id)
        .order_by(Room.id.desc())
    )
    return [(r, b) for r, b in rows.all()]


async def shares_room(session: AsyncSession, a: int, b: int) -> bool:
    """두 사람이 같은 대결방에 있는지(본인 포함)."""
    if a == b:
        return True
    other = select(RoomMember.room_id).where(RoomMember.user_id == b)
    return bool(
        await session.scalar(
            select(RoomMember.room_id).where(RoomMember.user_id == a, RoomMember.room_id.in_(other))
        )
    )
