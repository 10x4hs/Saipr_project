"""문단 반응과 친구 진행률 (PRD ROOM-03).

- 반응은 (책, 청크, 문단 번호)에 붙고, 그 책으로 같은 대결방에 있는 사람끼리 보인다.
- 스포일러 가드: 내가 검증받은 마지막 청크보다 뒤의 반응은 내용 없이 개수만 준다.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, LibraryEntry, Reaction, ReactionKind, Room, RoomMember, User

EMOJIS = ("❤️", "😂", "😮", "😢", "👏")
MAX_COMMENT = 140
MAX_ANCHOR = 2000


class ReactionError(ValueError):
    pass


@dataclass
class Friend:
    user_id: int
    nickname: str
    current_chunk: int
    verified_chunk: int


async def circle(session: AsyncSession, user_id: int, book_id: int) -> set[int]:
    """이 책으로 나와 같은 방에 있는 사람들(나 포함)."""
    my_rooms = (
        select(RoomMember.room_id)
        .join(Room, Room.id == RoomMember.room_id)
        .where(RoomMember.user_id == user_id, Room.book_id == book_id)
    )
    rows = await session.scalars(select(RoomMember.user_id).where(RoomMember.room_id.in_(my_rooms)))
    return set(rows) | {user_id}


async def verified_of(session: AsyncSession, user_id: int, book_id: int) -> int:
    v = await session.scalar(
        select(LibraryEntry.verified_chunk).where(
            LibraryEntry.user_id == user_id, LibraryEntry.book_id == book_id
        )
    )
    return -1 if v is None else v


async def add_reaction(
    session: AsyncSession,
    user: User,
    book: Book,
    chunk: int,
    anchor: int,
    emoji: str | None,
    comment: str | None,
) -> Reaction:
    if not 0 <= chunk < book.total_chunks:
        raise ReactionError("없는 쪽이에요")
    if not 0 <= anchor <= MAX_ANCHOR:
        raise ReactionError("없는 문단이에요")
    # 아직 펼치지도 않은 뒤쪽에는 반응을 달 수 없다 (지금 읽는 쪽까지)
    if chunk > await verified_of(session, user.id, book.id) + 1:
        raise ReactionError("아직 읽지 않은 쪽이에요")
    if comment and comment.strip():
        kind, body = ReactionKind.COMMENT, comment.strip()[:MAX_COMMENT]
    elif emoji in EMOJIS:
        kind, body = ReactionKind.EMOJI, emoji
    else:
        raise ReactionError("이모지나 한 줄 글이 필요해요")
    r = Reaction(user_id=user.id, book_id=book.id, chunk_index=chunk, anchor=anchor, kind=kind, body=body)
    session.add(r)
    await session.commit()
    return r


async def reactions_for(session: AsyncSession, user: User, book: Book, chunk: int) -> dict:
    """한 쪽의 반응. 내 검증 위치보다 뒤면 개수만(스포일러 가드)."""
    members = await circle(session, user.id, book.id)
    q = (
        select(Reaction, User.nickname)
        .join(User, User.id == Reaction.user_id)
        .where(Reaction.book_id == book.id, Reaction.chunk_index == chunk, Reaction.user_id.in_(members))
    )
    rows = (await session.execute(q.order_by(Reaction.id))).all()
    verified = await verified_of(session, user.id, book.id)
    # 내가 지금 읽고 있는 쪽(검증 직전)도 아직은 봉인 — 단, 내 반응은 늘 보인다
    if chunk > verified:
        mine = [_out(r, n, user.id) for r, n in rows if r.user_id == user.id]
        return {"chunk": chunk, "sealed": len(rows) - len(mine), "items": mine}
    return {"chunk": chunk, "sealed": 0, "items": [_out(r, n, user.id) for r, n in rows]}


async def sealed_ahead(session: AsyncSession, user: User, book: Book) -> int:
    """내 검증 위치보다 뒤에서 기다리는 친구 반응 수."""
    members = await circle(session, user.id, book.id) - {user.id}
    if not members:
        return 0
    verified = await verified_of(session, user.id, book.id)
    return (
        await session.scalar(
            select(func.count()).where(
                Reaction.book_id == book.id, Reaction.chunk_index > verified, Reaction.user_id.in_(members)
            )
        )
        or 0
    )


async def friends(session: AsyncSession, user: User, book: Book) -> list[Friend]:
    members = await circle(session, user.id, book.id) - {user.id}
    if not members:
        return []
    rows = await session.execute(
        select(User.id, User.nickname, LibraryEntry.current_chunk, LibraryEntry.verified_chunk)
        .outerjoin(LibraryEntry, (LibraryEntry.user_id == User.id) & (LibraryEntry.book_id == book.id))
        .where(User.id.in_(members))
    )
    return [Friend(uid, nick, cur or 0, -1 if ver is None else ver) for uid, nick, cur, ver in rows.all()]


def _out(r: Reaction, nickname: str, me: int) -> dict:
    return {
        "id": r.id,
        "anchor": r.anchor,
        "kind": r.kind,
        "body": r.body,
        "nickname": nickname,
        "mine": r.user_id == me,
    }


async def delete_reaction(session: AsyncSession, user: User, book: Book, reaction_id: int) -> Reaction | None:
    """내가 남긴 반응만 지운다. 남의 것이거나 없으면 None."""
    r = await session.get(Reaction, reaction_id)
    if r is None or r.book_id != book.id or r.user_id != user.id:
        return None
    await session.delete(r)
    await session.commit()
    return r
