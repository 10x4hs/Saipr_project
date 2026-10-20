"""WebSocket 채널 (PRD ROOM-02).

/ws/rooms/{room_id}?last_event_id=N
    방 이벤트: progress.updated · reaction.created · member.joined · presence.changed
/ws/me
    내 알림: notification.created

- 로그인 세션 쿠키로 인증하고, 다른 사이트에서 연 소켓(Origin 불일치)은 거절한다.
- 재연결 시 last_event_id 이후의 버퍼된 이벤트를 먼저 보낸다.
- sync 모드 방에서는 클라이언트가 {"type": "presence", "chunk_index": n}을 보내면 1초에 한 번까지 중계한다.
"""

import asyncio
import contextlib
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SESSION_USER
from app.db.session import get_session
from app.models import Room, RoomMode, User
from app.realtime.broker import Event, broker, room_channel, user_channel
from app.services import rooms as room_service

router = APIRouter()
PRESENCE_INTERVAL = 1.0


def _same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if origin is None:  # 브라우저가 아닌 클라이언트(테스트 등)
        return True
    return urlparse(origin).netloc == ws.headers.get("host")


async def _user(ws: WebSocket, session: AsyncSession) -> User | None:
    uid = ws.session.get(SESSION_USER) if "session" in ws.scope else None
    return await session.get(User, uid) if uid is not None else None


async def _pump(
    ws: WebSocket, channel: str, last_event_id: int | None, on_message=None, stop_on=None
) -> None:
    queue, replay = broker.subscribe(channel, last_event_id)
    try:
        for e in replay:
            await ws.send_json(e.as_json())

        async def forward() -> None:
            while True:
                e: Event = await queue.get()
                await ws.send_json(e.as_json())
                if stop_on is not None and stop_on(e):
                    await ws.close()
                    return

        async def receive() -> None:
            while True:
                msg = await ws.receive_json()
                if on_message is not None:
                    await on_message(msg)

        tasks = [asyncio.create_task(forward()), asyncio.create_task(receive())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            with contextlib.suppress(WebSocketDisconnect, asyncio.CancelledError):
                t.result()
    except WebSocketDisconnect:
        pass
    finally:
        broker.unsubscribe(channel, queue)


@router.websocket("/ws/rooms/{room_id}")
async def room_socket(
    ws: WebSocket,
    room_id: int,
    last_event_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> None:
    if not _same_origin(ws):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user = await _user(ws, session)
    room = await session.get(Room, room_id)
    allowed = (
        user is not None and room is not None and await room_service.is_member(session, room_id, user.id)
    )
    sync_mode = room is not None and room.mode is RoomMode.SYNC
    await session.close()  # 연결이 오래 유지되므로 DB 연결은 바로 돌려준다
    if not allowed:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()

    last_sent = 0.0

    async def on_message(msg: dict) -> None:
        nonlocal last_sent
        if msg.get("type") == "ping":
            await ws.send_json({"type": "pong"})
        elif msg.get("type") == "presence" and sync_mode and isinstance(msg.get("chunk_index"), int):
            now = time.monotonic()
            if now - last_sent >= PRESENCE_INTERVAL:
                last_sent = now
                room_service.publish_presence(room_id, user, msg["chunk_index"])

    def left_room(e: Event) -> bool:
        # 방을 나가면 연결할 때 확인한 멤버십이 끝난 것이므로 소켓도 닫는다
        return e.type == "member.left" and e.data.get("user_id") == user.id

    await _pump(ws, room_channel(room_id), last_event_id, on_message, left_room)


@router.websocket("/ws/me")
async def my_socket(ws: WebSocket, session: AsyncSession = Depends(get_session)) -> None:
    if not _same_origin(ws):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user = await _user(ws, session)
    await session.close()
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()
    await _pump(ws, user_channel(user.id), None)
