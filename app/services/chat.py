"""읽기방 채팅 (docs/plans/2026-10-20-native-app-design.md '읽기방 채팅').

- 방 멤버만 읽고 쓴다. 멤버가 아니면 방이 있는지도 알려 주지 않는다(404).
- 새 메시지는 커밋된 뒤 방 채널에 message.created로 나간다(본문 포함 — 채팅은 스포일러 가드 대상이 아니다).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import aware, utcnow
from app.db.session import defer_publish
from app.models import Room, RoomMessage, User
from app.realtime.broker import room_channel
from app.services import rooms
from app.services.rooms import RoomError

BODY_MAX = 500
PAGE_MAX = 100


async def member_room(session: AsyncSession, room_id: int, user: User) -> Room:
    room = await session.get(Room, room_id)
    if room is None or not await rooms.is_member(session, room_id, user.id):
        raise RoomError("방을 찾을 수 없어요.", 404)
    return room


def message_json(m: RoomMessage, author: User) -> dict:
    return {
        "id": m.id,
        "user": {"id": author.id, "nickname": author.nickname, "avatar_color": author.color},
        "body": m.body,
        "created_at": aware(m.created_at).isoformat(),
    }


async def history(
    session: AsyncSession, room: Room, before: int | None = None, limit: int = 50
) -> list[tuple[RoomMessage, User]]:
    """before보다 앞선 메시지 limit개를 오래된 → 새 순으로."""
    limit = max(1, min(PAGE_MAX, limit))
    q = (
        select(RoomMessage, User)
        .join(User, User.id == RoomMessage.user_id)
        .where(RoomMessage.room_id == room.id)
        .order_by(RoomMessage.id.desc())
        .limit(limit)
    )
    if before is not None:
        q = q.where(RoomMessage.id < before)
    rows = (await session.execute(q)).all()
    return [(m, u) for m, u in reversed(rows)]


async def post(
    session: AsyncSession, room: Room, user: User, body: str, now: datetime | None = None
) -> RoomMessage:
    body = body.strip()
    if not 1 <= len(body) <= BODY_MAX:
        raise RoomError(f"메시지는 1~{BODY_MAX}자로 써 주세요.")
    if room.archived:
        raise RoomError("보관된 방이에요.", 410)
    m = RoomMessage(room_id=room.id, user_id=user.id, body=body, created_at=now or utcnow())
    session.add(m)
    await session.flush()
    defer_publish(session, room_channel(room.id), "message.created", message_json(m, user))
    await session.commit()
    return m
