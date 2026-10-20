"""실시간 연결 (WebSocket) — 방 채널(진행률·반응·채팅·입장)과 내 채널(알림).

끊기면 1초 → 30초로 늘려 가며 다시 붙고, 마지막으로 받은 이벤트 id 이후부터 다시 받는다 (서버가 100건 보관).
화면은 subscribe(handler)로 이벤트를 받고, 화면을 떠날 때 unsubscribe한다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable

import websockets
import websockets.exceptions

log = logging.getLogger(__name__)
Handler = Callable[[dict], Awaitable[None] | None]


class Channel:
    def __init__(self, url: str, on_rejected: Callable[[str], None] | None = None) -> None:
        self.url = url
        self.on_rejected = on_rejected  # 서버가 인증·권한으로 거절했을 때 (다시 붙지 않는다)
        self.rejected = False
        self.handlers: set[Handler] = set()
        self.last_id: int | None = None
        self._task: asyncio.Task | None = None
        self._ws = None
        self.connected = False

    def subscribe(self, handler: Handler) -> None:
        self.handlers.add(handler)
        if self.rejected:
            return
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._run())

    def unsubscribe(self, handler: Handler) -> None:
        self.handlers.discard(handler)
        if not self.handlers:
            self.close()

    def close(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        self.connected = False

    async def send(self, data: dict) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps(data))

    async def _run(self) -> None:
        delay = 1.0
        while self.handlers:
            url = self.url if self.last_id is None else f"{self.url}&last_event_id={self.last_id}"
            try:
                async with websockets.connect(url, open_timeout=8, ping_interval=25) as ws:
                    self._ws, self.connected, delay = ws, True, 1.0
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except ValueError:
                            continue
                        if event.get("id"):
                            self.last_id = event["id"]
                        for h in list(self.handlers):
                            self._dispatch(h, event)
                if ws.close_code == 1008:
                    self._reject("closed 1008")
                    return
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.ConnectionClosed as e:
                if e.rcvd is not None and e.rcvd.code == 1008:  # 방에서 나갔거나 권한이 없다
                    self._reject("closed 1008")
                    return
                log.info("realtime reconnect in %.0fs (%s)", delay, type(e).__name__)
            except websockets.exceptions.InvalidStatus as e:
                if e.response.status_code in (401, 403):
                    self._reject(f"http {e.response.status_code}")
                    return
                log.info("realtime reconnect in %.0fs (%s)", delay, type(e).__name__)
            except Exception as e:  # 연결 실패·끊김 → 잠시 후 다시
                log.info("realtime reconnect in %.0fs (%s)", delay, type(e).__name__)
            finally:
                self._ws, self.connected = None, False
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    def _dispatch(self, handler: Handler, event: dict) -> None:
        """핸들러는 연결 task 밖에서 돈다 — 핸들러가 로그아웃(채널 닫기)을 불러도 자기 자신을 취소하지 않게."""
        try:
            result = handler(event)
        except Exception:  # 화면 하나의 오류가 연결을 끊지 않게
            log.exception("realtime handler failed")
            return
        if asyncio.iscoroutine(result):
            task = asyncio.ensure_future(result)
            _pending.add(task)
            task.add_done_callback(_finished)

    def _reject(self, why: str) -> None:
        log.info("realtime rejected (%s): %s", why, self.url.split("?")[0])
        self.rejected = True
        if self.on_rejected:
            self.on_rejected(self.url)


_pending: set[asyncio.Task] = set()


def _finished(task: asyncio.Task) -> None:
    _pending.discard(task)
    if not task.cancelled() and task.exception():
        log.error("realtime handler failed", exc_info=task.exception())


class Realtime:
    """채널 묶음. 같은 방은 연결 하나를 여러 화면이 같이 쓴다."""

    def __init__(self, url_for: Callable[[str], str], on_rejected: Callable[[str], None] | None = None) -> None:
        self.url_for = url_for
        self.on_rejected = on_rejected  # (path)
        self.channels: dict[str, Channel] = {}

    def channel(self, path: str) -> Channel:
        ch = self.channels.get(path)
        if ch is None:
            ch = self.channels[path] = Channel(self.url_for(path), (lambda _url, p=path: self.on_rejected(p)) if self.on_rejected else None)
        return ch

    def close_all(self) -> None:
        for ch in self.channels.values():
            ch.close()
        self.channels.clear()
