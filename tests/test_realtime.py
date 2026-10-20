"""실시간 동기화 (GOAL 검증 5).

시나리오: 사용자 A 방 생성 → B 초대 링크 입장 → A가 청크 검증 → B의 WebSocket이 1초 안에 progress.updated 수신.
실제 앱(세션 미들웨어 · 커밋 후 아웃박스 · 브로커 · WebSocket)을 그대로 쓰고, DB만 임시 SQLite 파일이다.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import models
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.realtime.broker import Broker

RECEIVE_TIMEOUT = 3.0


@pytest.fixture
def fresh_db():
    async def reset() -> int:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as s:
            book = models.Book(
                source="wikisource",
                external_id="봄봄",
                title="봄봄",
                language="ko",
                has_fulltext=True,
                total_chunks=3,
                chunks=[models.BookChunk(chunk_index=i, text="가" * 15, char_count=15) for i in range(3)],
            )
            s.add(book)
            await s.commit()
            return book.id

    book_id = asyncio.run(reset())
    yield book_id
    asyncio.run(engine.dispose())


def login(c: TestClient, nickname: str) -> None:
    token = c.get("/api/v1/auth/csrf").json()["csrf_token"]
    r = c.post(
        "/api/v1/auth/signup",
        json={
            "nickname": nickname,
            "email": f"{nickname}@rt.kr",
            "password": "password123",
            "password_confirm": "password123",
        },
        headers={"X-CSRF-Token": token},
    )
    assert r.status_code == 201, r.text
    c.headers["X-CSRF-Token"] = c.get("/api/v1/auth/csrf").json()["csrf_token"]


def receive(ws, pool: ThreadPoolExecutor) -> dict:
    """테스트가 멈추지 않도록 시간 제한을 두고 받는다."""
    return pool.submit(ws.receive_json).result(timeout=RECEIVE_TIMEOUT)


def test_e2e_progress_reaches_friend_within_one_second(fresh_db):
    book_id = fresh_db
    with TestClient(app) as a, TestClient(app) as b, ThreadPoolExecutor(1) as pool:
        login(a, "서연")
        room = a.post("/api/v1/rooms", json={"book_id": book_id, "name": "같이 읽기"}).json()

        login(b, "준호")
        assert b.get(f"/api/v1/invites/{room['invite_code']}").status_code == 200  # 미리보기
        assert b.post(f"/api/v1/invites/{room['invite_code']}/join").status_code == 200

        with b.websocket_connect(f"/ws/rooms/{room['id']}") as ws:
            ws.send_json({"type": "ping"})
            assert receive(ws, pool) == {"type": "pong"}

            started = time.perf_counter()
            r = a.post(
                f"/api/v1/books/{book_id}/events",
                json={
                    "events": [
                        {"chunk_index": 0, "dwell_ms": 2_000, "occurred_at": datetime.now(UTC).isoformat()}
                    ]
                },
            )
            assert r.json()["newly_verified"] == [0]
            event = receive(ws, pool)
            elapsed = time.perf_counter() - started

        assert event["type"] == "progress.updated"
        assert event["data"]["nickname"] == "서연"
        assert event["data"]["verified_chunk"] == 0 and event["data"]["progress_pct"] == 33
        assert elapsed < 1.0, f"{elapsed:.3f}s"

        # 재연결: 놓친 이벤트를 last_event_id 이후부터 다시 받는다
        with b.websocket_connect(f"/ws/rooms/{room['id']}?last_event_id=0") as ws:
            replayed = [receive(ws, pool) for _ in range(2)]
        assert [e["type"] for e in replayed] == ["member.joined", "progress.updated"]

        # 반응 이벤트에는 본문이 실리지 않는다 (받는 쪽 스포일러 가드를 거쳐 다시 조회)
        with b.websocket_connect(f"/ws/rooms/{room['id']}") as ws:
            a.post(
                f"/api/v1/books/{book_id}/reactions",
                json={"chunk_index": 0, "kind": "comment", "body": "비밀"},
            )
            rx = receive(ws, pool)
        assert rx["type"] == "reaction.created" and "비밀" not in str(rx)


def test_socket_rejects_outsiders_and_foreign_origin(fresh_db):
    book_id = fresh_db
    with TestClient(app) as a, TestClient(app) as stranger:
        login(a, "방장")
        room = a.post("/api/v1/rooms", json={"book_id": book_id, "name": "비밀방"}).json()
        login(stranger, "낯선이")
        for client, headers in ((stranger, {}), (a, {"origin": "https://evil.example"})):
            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect(f"/ws/rooms/{room['id']}", headers=headers) as ws,
            ):
                ws.receive_json()
        with pytest.raises(WebSocketDisconnect), TestClient(app).websocket_connect("/ws/me") as ws:
            ws.receive_json()


def test_socket_closes_after_leaving_room(fresh_db):
    """연결할 때만 멤버십을 확인하므로, 방을 나가면 열린 소켓도 닫혀야 한다."""
    book_id = fresh_db
    with TestClient(app) as a, TestClient(app) as b, ThreadPoolExecutor(1) as pool:
        login(a, "방장2")
        room = a.post("/api/v1/rooms", json={"book_id": book_id, "name": "나갈 방"}).json()
        login(b, "손님")
        b.post(f"/api/v1/invites/{room['invite_code']}/join")
        with b.websocket_connect(f"/ws/rooms/{room['id']}") as ws:
            assert b.post(f"/api/v1/rooms/{room['id']}/leave").status_code == 204
            assert receive(ws, pool)["type"] == "member.left"
            with pytest.raises(WebSocketDisconnect):
                receive(ws, pool)


def test_sync_mode_presence_is_relayed(fresh_db):
    book_id = fresh_db
    with TestClient(app) as a, TestClient(app) as b, ThreadPoolExecutor(1) as pool:
        login(a, "가")
        room = a.post("/api/v1/rooms", json={"book_id": book_id, "name": "동시", "mode": "sync"}).json()
        login(b, "나")
        b.post(f"/api/v1/invites/{room['invite_code']}/join")
        with (
            b.websocket_connect(f"/ws/rooms/{room['id']}") as wb,
            a.websocket_connect(f"/ws/rooms/{room['id']}") as wa,
        ):
            wa.send_json({"type": "presence", "chunk_index": 2})
            got = receive(wb, pool)
        assert got["type"] == "presence.changed" and got["data"]["chunk_index"] == 2


async def test_broker_buffer_keeps_last_100():
    br = Broker()
    for i in range(150):
        br.publish("room:1", "t", {"i": i})
    q, replay = br.subscribe("room:1", last_event_id=0)
    assert len(replay) == 100 and replay[0].data == {"i": 50}
    br.publish("room:1", "t", {"i": "live"})
    assert (await asyncio.wait_for(q.get(), 1)).data == {"i": "live"}
    br.unsubscribe("room:1", q)
    assert br.subscriber_count("room:1") == 0


def test_outbox_drops_events_on_rollback(fresh_db):
    from app.db.session import defer_publish
    from app.realtime.broker import broker

    async def run():
        async with SessionLocal() as s:
            defer_publish(s, "room:9", "x", {})
            await s.rollback()
            defer_publish(s, "room:9", "y", {})
            await s.commit()

    asyncio.run(run())
    _, replay = asyncio.run(_subscribe(broker))
    assert [e.type for e in replay] == ["y"]


async def _subscribe(br):
    q, replay = br.subscribe("room:9", 0)
    br.unsubscribe("room:9", q)
    return q, replay


def test_invite_expiry_is_seven_days(fresh_db):
    with TestClient(app) as a:
        login(a, "만료확인")
        room = a.post("/api/v1/rooms", json={"book_id": fresh_db, "name": "x"}).json()
    expires = datetime.fromisoformat(room["invite_expires_at"])
    expires = expires if expires.tzinfo else expires.replace(tzinfo=UTC)
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)
