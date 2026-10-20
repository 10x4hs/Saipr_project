"""읽은 기록 보내기 · 실시간 채널 거절 — 기록이 사라지거나 섞이지 않는가."""

import asyncio
import json

import httpx
import pytest
import websockets

from saipr.core.api import Api
from saipr.core.reading import EventQueue
from saipr.core.realtime import Channel
from saipr.core.store import Store
from saipr.core.sync import ReadingSync, SessionExpired
from tests.test_core import FakePrefs


def ev(i, at):
    return {"chunk_index": i, "dwell_ms": 1000, "occurred_at": at}


def make(handler, user=None):
    user = {"id": 1} if user is None else user
    api = Api("http://test", transport=httpx.MockTransport(handler))
    api.token = "tok"
    store = Store(FakePrefs())
    return api, store, ReadingSync(api, store, lambda: user.get("id"))


def ok(req):
    return httpx.Response(200, json={"verified_chunk": 0, "progress_pct": 10, "newly_verified": []})


async def test_success_acks_and_clears_pending_list():
    api, store, sync = make(ok)
    q = EventQueue([ev(0, "2026-10-20T00:00:00Z")])
    assert (await sync.send(5, q))["progress_pct"] == 10
    assert len(q) == 0 and await store.get("queued_books.1") == []


@pytest.mark.parametrize("status", [403, 429, 500, 503])
async def test_retryable_errors_keep_the_queue(status):
    api, store, sync = make(lambda req: httpx.Response(status, json={"detail": "x"}))
    q = EventQueue([ev(0, "a"), ev(1, "b")])
    assert await sync.send(5, q) is None
    assert len(q) == 2 and len(await store.get("queue.1.5")) == 2


async def test_session_expired_keeps_queue_and_raises():
    api, store, sync = make(lambda req: httpx.Response(401, json={"detail": "x"}))
    q = EventQueue([ev(0, "a")])
    with pytest.raises(SessionExpired):
        await sync.send(5, q)
    assert len(q) == 1 and await store.get("queued_books.1") == [5]


async def test_final_rejection_drops_the_batch():
    api, store, sync = make(lambda req: httpx.Response(422, json={"detail": "x"}))
    q = EventQueue([ev(0, "a")])
    await sync.send(5, q)
    assert len(q) == 0


async def test_no_token_does_not_send():
    calls = []
    api, store, sync = make(lambda req: calls.append(req) or ok(req))
    api.token = None
    q = EventQueue([ev(0, "a")])
    assert await sync.send(5, q) is None and calls == [] and len(q) == 1


async def test_concurrent_flushes_do_not_drop_unsent_events():
    sent = []

    async def slow(req):
        await asyncio.sleep(0.01)
        sent.extend(json.loads(req.content)["events"])
        return ok(req)

    api = Api("http://test", transport=httpx.MockTransport(slow))
    api.token = "tok"
    sync = ReadingSync(api, Store(FakePrefs()), lambda: 1)
    q = EventQueue([ev(0, "a")])
    first = asyncio.ensure_future(sync.send(5, q))
    await asyncio.sleep(0)
    q.push([ev(1, "b")])  # 첫 전송 중에 새 기록이 쌓인다
    await asyncio.gather(first, sync.send(5, q))
    assert [e["chunk_index"] for e in sent] == [0, 1] and len(q) == 0


async def test_pending_books_are_sent_oldest_first_and_per_account():
    order = []

    def handler(req):
        order.append(req.url.path.split("/")[-2])
        return ok(req)

    user = {"id": 1}
    api, store, sync = make(handler, user)
    await sync.save(7, EventQueue([ev(0, "2026-10-20T02:00:00Z")]))
    await sync.save(3, EventQueue([ev(0, "2026-10-20T01:00:00Z")]))
    user["id"] = 2  # 다른 계정 — 1번 계정의 기록을 보내면 안 된다
    await sync.send_pending()
    assert order == []
    user["id"] = 1
    await sync.send_pending()
    assert order == ["3", "7"]


async def test_channel_stops_when_server_rejects():
    async def reject(conn, request):
        return conn.respond(403, "no")

    rejected = []
    async with websockets.serve(lambda ws: None, "127.0.0.1", 0, process_request=reject) as server:
        port = server.sockets[0].getsockname()[1]
        ch = Channel(f"ws://127.0.0.1:{port}/ws/me?token=x", rejected.append)
        ch.subscribe(lambda e: None)
        await asyncio.wait_for(ch._task, 3)
    assert ch.rejected and len(rejected) == 1
