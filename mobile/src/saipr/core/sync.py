"""읽은 기록 보내기 — 계정마다 · 책마다 기기에 쌓아 두고, 한 번에 하나씩 서버로 보낸다.

- 보내기 전에 먼저 저장한다(앱이 죽어도 남는다).
- 다시 보내도 결과가 같은 거절(400 · 404 · 409 · 410 · 422)만 큐에서 지운다.
  401(로그인 만료) · 403 · 429 · 5xx · 오프라인은 남겨 두고 나중에 다시 보낸다.
- 로그인할 때 밀린 기록을 오래된 것부터 먼저 보낸다(서버는 이벤트 시각 순서로 인정한다).
- 큐 키에 사용자 id가 들어가서, 다른 계정으로 로그인해도 기록이 섞이지 않는다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from saipr.core.api import Api, ApiError, Offline
from saipr.core.reading import EventQueue
from saipr.core.store import Store

FINAL = {400, 404, 409, 410, 422}


class SessionExpired(Exception):
    pass


class ReadingSync:
    def __init__(self, api: Api, store: Store, user_id: Callable[[], int | None]) -> None:
        self.api, self.store, self.user_id = api, store, user_id
        self.lock = asyncio.Lock()

    def _key(self, book_id: int) -> str:
        return f"queue.{self.user_id()}.{book_id}"

    def _books_key(self) -> str:
        return f"queued_books.{self.user_id()}"

    async def load(self, book_id: int) -> EventQueue:
        return EventQueue(list(await self.store.get(self._key(book_id), []) or []))

    async def save(self, book_id: int, queue: EventQueue) -> None:
        await self.store.set(self._key(book_id), queue.items)
        books = list(await self.store.get(self._books_key(), []) or [])
        if len(queue) and book_id not in books:
            await self.store.set(self._books_key(), [*books, book_id])
        elif not len(queue) and book_id in books:
            await self.store.set(self._books_key(), [b for b in books if b != book_id])

    async def send(self, book_id: int, queue: EventQueue) -> dict | None:
        """한 배치를 보낸다. 서버 응답(진행률)을 돌려주고, 보내지 못했으면 None. 로그인이 만료됐으면 SessionExpired."""
        async with self.lock:
            if not len(queue) or not self.api.token or self.user_id() is None:
                return None
            batch = queue.batch()
            await self.save(book_id, queue)
            try:
                r = await self.api.post(f"/books/{book_id}/events", {"events": batch})
            except Offline:
                return None
            except ApiError as e:
                if e.status == 401:
                    raise SessionExpired from e
                if e.status in FINAL:
                    queue.ack(len(batch))
                    await self.save(book_id, queue)
                return None
            queue.ack(len(batch))
            await self.save(book_id, queue)
            return r

    async def send_pending(self, skip: set[int] | None = None) -> None:
        """밀린 책들의 기록을 오래된 이벤트부터 모두 보낸다(로그인 직후)."""
        books = [b for b in (await self.store.get(self._books_key(), []) or []) if b not in (skip or set())]
        queues = {b: await self.load(b) for b in books}
        order = sorted((b for b in books if len(queues[b])), key=lambda b: queues[b].items[0].get("occurred_at", ""))
        for b in order:
            while len(queues[b]):
                before = len(queues[b])
                await self.send(b, queues[b])
                if len(queues[b]) == before:
                    return  # 오프라인 · 서버 오류 — 다음 기회에
            await self.save(b, queues[b])
