"""방·사용자 채널 이벤트 브로커 (PRD ROOM-02).

MVP는 단일 인스턴스라 인메모리로 둔다. 다중 인스턴스로 갈 때는 같은 publish/subscribe
인터페이스로 Redis Pub/Sub 구현을 추가하면 된다.

- 채널마다 최근 100건을 버퍼에 남겨, 재연결한 클라이언트가 last_event_id 이후를 다시 받는다.
- publish는 동기 함수다. DB 커밋 직후 훅(app/db/session.py)에서 바로 부를 수 있게 하기 위해서다.
"""

import asyncio
import itertools
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

BUFFER_SIZE = 100
QUEUE_SIZE = 500


@dataclass(slots=True, frozen=True)
class Event:
    id: int
    channel: str
    type: str
    data: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "data": self.data}


@dataclass
class Broker:
    buffer_size: int = BUFFER_SIZE
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _buffers: dict[str, deque[Event]] = field(default_factory=dict)
    _subs: dict[str, set[asyncio.Queue[Event]]] = field(default_factory=lambda: defaultdict(set))
    _loops: dict[int, asyncio.AbstractEventLoop] = field(default_factory=dict)

    def publish(self, channel: str, type: str, data: dict[str, Any]) -> Event:
        event = Event(next(self._ids), channel, type, data)
        self._buffers.setdefault(channel, deque(maxlen=self.buffer_size)).append(event)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        for q in list(self._subs.get(channel, ())):
            loop = self._loops.get(id(q))
            if loop is not None and loop is not current:
                # 다른 이벤트 루프(스레드)의 구독자에게는 그 루프에서 넣는다.
                # asyncio.Queue는 스레드 안전하지 않다.
                loop.call_soon_threadsafe(self._put, q, event)
            else:
                self._put(q, event)
        return event

    @staticmethod
    def _put(q: asyncio.Queue[Event], event: Event) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # 너무 느린 구독자는 이벤트를 놓친다. 재연결하면 버퍼에서 다시 받는다.
            pass

    def subscribe(
        self, channel: str, last_event_id: int | None = None
    ) -> tuple[asyncio.Queue[Event], list[Event]]:
        q: asyncio.Queue[Event] = asyncio.Queue(QUEUE_SIZE)
        self._subs[channel].add(q)
        self._loops[id(q)] = asyncio.get_running_loop()
        replay = (
            [e for e in self._buffers.get(channel, ()) if e.id > last_event_id]
            if last_event_id is not None
            else []
        )
        return q, replay

    def unsubscribe(self, channel: str, q: asyncio.Queue[Event]) -> None:
        self._loops.pop(id(q), None)
        subs = self._subs.get(channel)
        if subs is not None:
            subs.discard(q)
            if not subs:
                del self._subs[channel]

    def subscriber_count(self, channel: str) -> int:
        return len(self._subs.get(channel, ()))

    def reset(self) -> None:
        self._buffers.clear()
        self._subs.clear()
        self._loops.clear()


broker = Broker()


def room_channel(room_id: int) -> str:
    return f"room:{room_id}"


def user_channel(user_id: int) -> str:
    return f"user:{user_id}"
