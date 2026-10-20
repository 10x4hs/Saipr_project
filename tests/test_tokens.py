"""네이티브 앱 Bearer 토큰 · 프로필 (docs/plans/2026-10-20-native-app-design.md '인증')."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.models import FRIEND_CODE_ALPHABET, ApiToken, User
from app.services.tokens import hash_token
from tests.conftest import make_book, signup, token_signup

ME_FIELDS = {
    "id",
    "nickname",
    "email",
    "spoiler_guard",
    "friend_code",
    "bio",
    "avatar_color",
    "daily_goal_minutes",
    "yearly_goal_books",
}


async def test_token_signup_login_and_me(api, session_factory):
    async with api() as c:
        me = await token_signup(c, "앱서연", "app@test.kr")
        assert set(me) == ME_FIELDS
        assert (
            len(me["friend_code"]) == 6 and me["daily_goal_minutes"] == 20 and me["yearly_goal_books"] == 12
        )
        assert me["avatar_color"].startswith("#")
        r = await c.get("/api/v1/auth/me")
        assert r.status_code == 200 and r.json() == me
        # 토큰 로그인은 쿠키 세션을 만들지 않는다
        assert "saipr_session" not in c.cookies

    async with api() as c:
        bad = await c.post("/api/v1/auth/token", json={"email": "app@test.kr", "password": "wrong-pass"})
        assert bad.status_code == 401 and bad.json()["detail"] == "이메일 또는 비밀번호가 맞지 않아요."
        r = await c.post("/api/v1/auth/token", json={"email": "APP@test.kr ", "password": "password123"})
        assert r.status_code == 200
        token = r.json()["token"]
        assert r.json()["user"]["id"] == me["id"]

    # DB에는 해시만 남는다
    async with session_factory() as s:
        rows = list(await s.scalars(select(ApiToken)))
    assert len(rows) == 2 and all(t.token_hash != token for t in rows)
    assert hash_token(token) in {t.token_hash for t in rows}
    assert all(t.expires_at.replace(tzinfo=UTC) - datetime.now(UTC) > timedelta(days=89) for t in rows)


async def test_signup_errors_are_korean(api):
    async with api() as c:
        r = await c.post(
            "/api/v1/auth/token/signup",
            json={"nickname": "", "email": "x", "password": "short", "password_confirm": "short"},
        )
        assert r.status_code == 400
        assert set(r.json()["errors"]) == {"nickname", "email", "password"}


async def test_bearer_skips_csrf_but_cookie_session_does_not(api):
    async with api() as c:
        await token_signup(c, "토큰")
        r = await c.put("/api/v1/auth/me/profile", json={"bio": "  안녕하세요  "})
        assert r.status_code == 200 and r.json()["bio"] == "안녕하세요"

    async with api() as c:
        await signup(c, "쿠키")
        del c.headers["X-CSRF-Token"]
        r = await c.put("/api/v1/auth/me/profile", json={"bio": "x"})
        assert r.status_code == 403  # 쿠키 세션은 여전히 CSRF 토큰이 필요하다


async def test_bad_or_expired_token_is_401_and_never_falls_back_to_cookie(api, session_factory):
    async with api() as c:
        await signup(c, "둘다")
        c.headers["Authorization"] = "Bearer not-a-real-token"
        assert (await c.get("/api/v1/auth/me")).status_code == 401
        r = await c.put("/api/v1/auth/me/settings", json={"spoiler_guard": False})
        assert r.status_code == 401 and r.json()["detail"] == "로그인이 만료됐어요. 다시 로그인해 주세요."

    async with api() as c:
        await token_signup(c, "만료")
        async with session_factory() as s:
            await s.execute(update(ApiToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
            await s.commit()
        assert (await c.get("/api/v1/auth/me")).status_code == 401
    async with session_factory() as s:
        assert await s.scalar(select(ApiToken)) is None  # 만료된 토큰은 지운다


async def test_revoke_token(api):
    async with api() as c:
        await token_signup(c, "로그아웃")
        assert (await c.get("/api/v1/auth/me")).status_code == 200
        assert (await c.delete("/api/v1/auth/token")).status_code == 204
        assert (await c.get("/api/v1/auth/me")).status_code == 401
        assert (await c.delete("/api/v1/auth/token")).status_code == 401
        del c.headers["Authorization"]
        assert (await c.delete("/api/v1/auth/token")).status_code == 401


async def test_existing_endpoints_work_with_bearer(api, session_factory):
    book = await make_book(session_factory, [["가" * 30]] * 2)
    async with api() as c:
        await token_signup(c, "방장")
        r = await c.post("/api/v1/rooms", json={"book_id": book, "name": "토큰방"})
        assert r.status_code == 201, r.text
        assert (await c.get("/api/v1/library")).status_code == 200
        assert (await c.get("/api/v1/points")).status_code == 200


async def test_profile_update_validates_everything_or_nothing(api):
    async with api() as c:
        me = await token_signup(c, "목표")
        r = await c.put(
            "/api/v1/auth/me/profile",
            json={
                "nickname": "새이름",
                "daily_goal_minutes": 0,
                "yearly_goal_books": 1000,
                "bio": "가" * 161,
            },
        )
        assert r.status_code == 400
        assert set(r.json()["errors"]) == {"daily_goal_minutes", "yearly_goal_books", "bio"}
        assert (await c.get("/api/v1/auth/me")).json()["nickname"] == "목표"  # 하나도 안 바뀐다

        r = await c.put(
            "/api/v1/auth/me/profile",
            json={
                "nickname": " 새이름 ",
                "daily_goal_minutes": 45,
                "yearly_goal_books": 24,
                "spoiler_guard": False,
                "avatar_color": "#ef4444",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert (body["nickname"], body["daily_goal_minutes"], body["yearly_goal_books"]) == ("새이름", 45, 24)
        assert body["spoiler_guard"] is False and body["avatar_color"] == "#ef4444"
        assert body["friend_code"] == me["friend_code"]

        r = await c.put("/api/v1/auth/me/profile", json={"avatar_color": "javascript:alert(1)"})
        assert r.status_code == 400 and "avatar_color" in r.json()["errors"]
        r = await c.put("/api/v1/auth/me/profile", json={"spoiler_guard": None})
        assert r.status_code == 400


async def test_friend_codes_are_unique(api, session_factory):
    async with api() as c:
        for i in range(5):
            await token_signup(c, f"코드{i}")
    async with session_factory() as s:
        codes = list(await s.scalars(select(User.friend_code)))
    assert len(set(codes)) == 5
    assert all(len(x) == 6 and set(x) <= set(FRIEND_CODE_ALPHABET) for x in codes)


# ── WebSocket ?token= (실제 앱 엔진 · 세션 미들웨어) ─────────────────────


@pytest.fixture
def ws_db():
    import asyncio

    from app import models
    from app.db.base import Base
    from app.db.session import SessionLocal, engine

    async def reset() -> int:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as s:
            book = models.Book(
                source="wikisource",
                external_id="토큰책",
                title="토큰책",
                language="ko",
                has_fulltext=True,
                total_chunks=1,
                chunks=[models.BookChunk(chunk_index=0, text="가" * 15, char_count=15)],
            )
            s.add(book)
            await s.commit()
            return book.id

    book_id = asyncio.run(reset())
    yield book_id
    asyncio.run(engine.dispose())


def _token(c: TestClient, nickname: str) -> str:
    r = c.post(
        "/api/v1/auth/token/signup",
        json={
            "nickname": nickname,
            "email": f"{nickname.encode().hex()}@ws.kr",
            "password": "password123",
            "password_confirm": "password123",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["token"]


def test_websocket_accepts_token_and_skips_origin_check(ws_db):
    with TestClient(app) as c, ThreadPoolExecutor(1) as pool:
        token = _token(c, "소켓")
        auth = {"Authorization": f"Bearer {token}"}
        room = c.post("/api/v1/rooms", json={"book_id": ws_db, "name": "앱방"}, headers=auth).json()
        # 네이티브 앱은 Origin이 없거나 제각각이다 — 토큰이 있으면 Origin을 보지 않는다
        with c.websocket_connect(
            f"/ws/rooms/{room['id']}?token={token}", headers={"origin": "app://flet"}
        ) as ws:
            ws.send_json({"type": "ping"})
            assert pool.submit(ws.receive_json).result(timeout=3) == {"type": "pong"}
            r = c.post(f"/api/v1/rooms/{room['id']}/messages", json={"body": "안녕"}, headers=auth)
            assert r.status_code == 201
            event = pool.submit(ws.receive_json).result(timeout=3)
        assert event["type"] == "message.created" and event["data"]["body"] == "안녕"
        assert set(event["data"]["user"]) == {"id", "nickname", "avatar_color"}

        with c.websocket_connect(f"/ws/me?token={token}") as ws:
            ws.send_json({"type": "ping"})

        for url in (f"/ws/rooms/{room['id']}?token=wrong", "/ws/me?token=wrong"):
            with pytest.raises(WebSocketDisconnect), c.websocket_connect(url) as ws:
                ws.receive_json()


def test_revoking_a_token_closes_its_open_sockets(ws_db):
    """로그아웃하면 그 토큰으로 열린 소켓(내 채널 · 방)도 1008로 끊긴다. 다른 토큰의 소켓은 그대로다."""
    with TestClient(app) as c, ThreadPoolExecutor(2) as pool:
        token = _token(c, "폐기")
        auth = {"Authorization": f"Bearer {token}"}
        room = c.post("/api/v1/rooms", json={"book_id": ws_db, "name": "닫힐방"}, headers=auth).json()
        with (
            c.websocket_connect(f"/ws/me?token={token}") as me,
            c.websocket_connect(f"/ws/rooms/{room['id']}?token={token}") as rs,
        ):
            rs.send_json({"type": "ping"})
            assert pool.submit(rs.receive_json).result(timeout=3) == {"type": "pong"}
            assert c.delete("/api/v1/auth/token", headers=auth).status_code == 204
            for ws in (me, rs):
                with pytest.raises(WebSocketDisconnect) as e:
                    pool.submit(ws.receive_json).result(timeout=3)
                assert e.value.code == 1008


def test_access_logs_hide_tokens():
    import logging

    from app.main import RedactTokens

    r = logging.LogRecord(
        "uvicorn.error",
        20,
        "",
        0,
        '%s - "WebSocket %s" [accepted]',
        ("1.2.3.4", "/ws/me?token=SECRET&x=1"),
        None,
    )
    RedactTokens().filter(r)
    assert "SECRET" not in r.getMessage() and "token=***&x=1" in r.getMessage()
