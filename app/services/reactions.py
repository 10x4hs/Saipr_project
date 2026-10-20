"""문단 반응 겹쳐보기 + 스포일러 가드 (PRD ROOM-03).

반응은 (도서, 청크, 문단 앵커)에 붙는다. 트래커 도서는 문단이 없으므로 chunk_index = 진행률 10% 구간(0~9).
스포일러 가드가 켜져 있으면 내 위치보다 뒤 반응은 본문 없이 개수만 돌려준다.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.db.session import defer_publish
from app.models import Book, Reaction, ReactionKind, Room, RoomMember, User
from app.realtime.broker import room_channel
from app.services import library, rooms
from app.services.notifications import notify

EMOJIS = ("❤️", "😂", "😮", "😢", "👍")
TRACKER_BUCKETS = 10


class ReactionError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(slots=True)
class ReactionView:
    id: int
    user_id: int
    nickname: str
    chunk_index: int
    anchor: int
    kind: str
    body: str
    created_at: datetime


@dataclass(slots=True)
class ReactionFeed:
    position: int
    spoiler_guard: bool
    visible: list[ReactionView] = field(default_factory=list)
    # 청크별 잠긴 반응 수 — "🔒 앞에서 N개의 반응이 기다리고 있어요"
    locked: dict[int, int] = field(default_factory=dict)

    @property
    def locked_total(self) -> int:
        return sum(self.locked.values())


async def create(
    session: AsyncSession,
    user: User,
    book: Book,
    chunk_index: int,
    anchor: int,
    kind: ReactionKind,
    body: str,
    now: datetime | None = None,
) -> Reaction:
    now = now or utcnow()
    body = body.strip()
    limit = book.total_chunks if book.has_fulltext else TRACKER_BUCKETS
    if not 0 <= chunk_index < limit:
        raise ReactionError("위치가 책 범위를 벗어났어요.")
    if not 0 <= anchor < 1000:
        raise ReactionError("문단 번호가 올바르지 않아요.")
    if not book.has_fulltext:
        anchor = 0
    if kind is ReactionKind.EMOJI and body not in EMOJIS:
        raise ReactionError(f"이모지는 {' '.join(EMOJIS)} 중에서 골라 주세요.")
    if kind is ReactionKind.COMMENT and not 1 <= len(body) <= 280:
        raise ReactionError("한줄평은 1~280자로 써 주세요.")

    entry = await library.get_entry(session, user.id, book.id)
    # 지금 읽고 있는 청크(검증 위치 + 1)까지만 반응할 수 있다. 안 읽은 곳에 반응을 남기는 건 막는다.
    if chunk_index > library.position_of(entry, book) + 1:
        raise ReactionError("아직 읽지 않은 위치에는 반응을 남길 수 없어요.", 403)

    reaction = Reaction(
        user_id=user.id,
        book_id=book.id,
        chunk_index=chunk_index,
        anchor=anchor,
        kind=kind,
        body=body,
        created_at=now,
    )
    session.add(reaction)
    await session.flush()

    # 본문은 싣지 않는다. 받는 쪽이 자기 스포일러 가드를 거쳐 다시 조회한다.
    room_rows = await session.scalars(
        select(Room.id)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .where(RoomMember.user_id == user.id, Room.book_id == book.id, Room.archived.is_(False))
    )
    for room_id in room_rows:
        defer_publish(
            session,
            room_channel(room_id),
            "reaction.created",
            {
                "reaction_id": reaction.id,
                "user_id": user.id,
                "nickname": user.nickname,
                "chunk_index": chunk_index,
                "anchor": anchor,
            },
        )

    # 같은 문단에 먼저 반응을 남긴 사람에게 "내 문단에 반응" 알림
    earlier = await session.scalars(
        select(Reaction.user_id)
        .distinct()
        .where(
            Reaction.book_id == book.id,
            Reaction.chunk_index == chunk_index,
            Reaction.anchor == anchor,
            Reaction.user_id != user.id,
        )
    )
    for uid in earlier:
        await notify(
            session,
            uid,
            "reaction",
            f"{user.nickname}님이 내가 반응한 문단에 반응을 남겼어요.",
            f"/books/{book.id}/read?chunk={chunk_index}",
            now,
        )
    await session.commit()
    return reaction


async def feed(
    session: AsyncSession,
    viewer: User,
    book: Book,
    room: Room | None = None,
    chunk_from: int | None = None,
    chunk_to: int | None = None,
) -> ReactionFeed:
    """보이는 반응 목록과 잠긴 반응 개수. room이 있으면 그 방 멤버들의 반응, 없으면 내 반응만."""
    if room is not None:
        if room.book_id != book.id:
            raise ReactionError("이 방의 책이 아니에요.")
        if not await rooms.is_member(session, room.id, viewer.id):
            raise ReactionError("방 멤버만 반응을 볼 수 있어요.", 403)
        authors = await rooms.member_ids(session, room.id)
    else:
        authors = [viewer.id]

    position = library.position_of(await library.get_entry(session, viewer.id, book.id), book)
    result = ReactionFeed(position=position, spoiler_guard=viewer.spoiler_guard)

    cond = [Reaction.book_id == book.id, Reaction.user_id.in_(authors)]
    if chunk_from is not None:
        cond.append(Reaction.chunk_index >= chunk_from)
    if chunk_to is not None:
        cond.append(Reaction.chunk_index <= chunk_to)

    # 내가 쓴 반응과 내 위치까지의 반응은 그대로, 그 뒤는 개수만
    open_cond = (Reaction.user_id == viewer.id) | (Reaction.chunk_index <= position)
    if viewer.spoiler_guard:
        locked_rows = await session.execute(
            select(Reaction.chunk_index, func.count()).where(*cond, ~open_cond).group_by(Reaction.chunk_index)
        )
        result.locked = {i: n for i, n in locked_rows.all()}
        cond.append(open_cond)

    rows = await session.execute(
        select(Reaction, User.nickname)
        .join(User, User.id == Reaction.user_id)
        .where(*cond)
        .order_by(Reaction.chunk_index, Reaction.anchor, Reaction.id)
    )
    result.visible = [
        ReactionView(r.id, r.user_id, nick, r.chunk_index, r.anchor, r.kind.value, r.body, r.created_at)
        for r, nick in rows.all()
    ]
    return result
