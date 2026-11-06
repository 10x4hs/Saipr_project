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

from app.models import Book, LibraryEntry, RacePresence, RaceQuote, Room, RoomMember, User

# 헷갈리는 글자(0/O, 1/I/L)를 뺀 코드 문자
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 6
DURATIONS = (1, 3, 7, 14)
MAX_MEMBERS = 8
PRESENCE_TTL = dt.timedelta(seconds=30)  # 이보다 오래 소식이 없으면 '지금 읽는 중'에서 뺀다
MAX_QUOTE = 280
QUOTE_FEED = 50


def clock() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)  # SQLite는 시간대를 저장하지 않는다


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


# ── 함께 읽는 중(presence) ─────────────────────────────────────────────


@dataclass
class Present:
    user: User
    room_id: int
    chunk_index: int


async def rooms_for_book(session: AsyncSession, user_id: int, book_id: int) -> list[Room]:
    """이 책으로 내가 들어가 있는 대결방들."""
    rows = await session.scalars(
        select(Room)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .where(RoomMember.user_id == user_id, Room.book_id == book_id)
        .order_by(Room.id)
    )
    return list(rows)


async def heartbeat(session: AsyncSession, user: User, book: Book, chunk: int) -> list[Room]:
    """지금 펼친 쪽을 내 모든 대결방(같은 책)에 기록한다. 기록한 방들을 돌려준다."""
    chunk = min(max(chunk, 0), max(book.total_chunks - 1, 0))
    rooms = await rooms_for_book(session, user.id, book.id)
    now = clock()
    for room in rooms:
        row = await session.get(RacePresence, (room.id, user.id))
        if row is None:
            session.add(RacePresence(room_id=room.id, user_id=user.id, chunk_index=chunk, last_seen=now))
        else:
            row.chunk_index, row.last_seen = chunk, now
    if rooms:
        await session.commit()
    return rooms


async def present(session: AsyncSession, room_ids: list[int], exclude: int | None = None) -> list[Present]:
    """최근에 심장박동을 보낸 사람들 — 한 사람이 여러 방에 있어도 한 번만."""
    if not room_ids:
        return []
    rows = await session.execute(
        select(RacePresence, User)
        .join(User, User.id == RacePresence.user_id)
        .where(RacePresence.room_id.in_(room_ids))
        .order_by(RacePresence.last_seen.desc())
    )
    cutoff = clock() - PRESENCE_TTL
    seen: dict[int, Present] = {}
    for p, u in rows.all():
        if u.id == exclude or u.id in seen or _aware(p.last_seen) < cutoff:
            continue
        seen[u.id] = Present(user=u, room_id=p.room_id, chunk_index=p.chunk_index)
    return list(seen.values())


# ── 문장 공유 ─────────────────────────────────────────────────────────


class QuoteError(ValueError):
    pass


async def _verified(session: AsyncSession, user_id: int, book_id: int) -> int:
    v = await session.scalar(
        select(LibraryEntry.verified_chunk).where(
            LibraryEntry.user_id == user_id, LibraryEntry.book_id == book_id
        )
    )
    return -1 if v is None else v


def clean_quote(text: str) -> str:
    return " ".join((text or "").split())[:MAX_QUOTE]


async def add_quote(session: AsyncSession, room: Room, user: User, chunk: int, text: str) -> RaceQuote:
    book = await session.get(Book, room.book_id)
    body = clean_quote(text)
    if not body:
        raise QuoteError("공유할 문장을 골라 주세요")
    if book is None or not 0 <= chunk < book.total_chunks:
        raise QuoteError("없는 쪽이에요")
    # 반응과 같은 규칙: 지금 읽는 쪽까지만
    if chunk > await _verified(session, user.id, book.id) + 1:
        raise QuoteError("아직 읽지 않은 쪽이에요")
    q = RaceQuote(room_id=room.id, user_id=user.id, chunk_index=chunk, body=body)
    session.add(q)
    await session.commit()
    return q


async def quotes(session: AsyncSession, room: Room, me_id: int) -> list[dict]:
    """방 피드(최신순). 내 검증 위치보다 뒤 쪽의 문장은 봉인한다 — 내 것은 늘 보인다."""
    verified = await _verified(session, me_id, room.book_id)
    rows = await session.execute(
        select(RaceQuote, User)
        .join(User, User.id == RaceQuote.user_id)
        .where(RaceQuote.room_id == room.id)
        .order_by(RaceQuote.id.desc())
        .limit(QUOTE_FEED)
    )
    out = []
    for q, u in rows.all():
        sealed = q.chunk_index > verified and u.id != me_id
        out.append(
            {
                "id": q.id,
                "user_id": u.id,
                "nickname": u.nickname,
                "chunk": q.chunk_index,
                "text": None if sealed else q.body,
                "sealed": sealed,
                "me": u.id == me_id,
                "at": _aware(q.created_at).isoformat() if q.created_at else None,
            }
        )
    return out
