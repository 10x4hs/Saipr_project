import re
import time

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_http_client
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from tests.conftest import mock_client, read_chunk, signup
from tests.test_api import upstream


def token_of(html: str) -> str:
    return re.search(r'<meta name="csrf" content="([^"]+)"', html).group(1)


async def _race_pair(host, friend) -> str:
    """호스트가 '긴글'(3쪽)로 대결을 열고 친구가 참가한 상태. 책 id를 돌려준다."""
    await signup(host, email="host@example.com", nickname="호스트")
    await signup(friend, email="friend@example.com", nickname="친구")
    page = await host.get("/races")
    r = await host.post("/races/start/wikisource/긴글", data={"csrf": token_of(page.text), "days": "7"})
    race = await host.get(r.headers["location"])
    code = re.search(r'id="code">([A-Z0-9]{6})<', race.text).group(1)
    preview = await friend.get(f"/join/{code}")
    await friend.post(f"/join/{code}", data={"csrf": token_of(preview.text)})
    book_id = re.search(r'href="/books/(\d+)"', race.text).group(1)
    return book_id


async def test_spoiler_guard_hides_reactions_ahead_of_me(api, clock):
    """GOAL #7: 내 검증 위치보다 뒤 청크의 반응은 본문 없이 개수만."""
    async with api(upstream) as host, api(upstream) as friend, api(upstream) as stranger:
        book_id = await _race_pair(host, friend)
        ht = token_of((await host.get(f"/books/{book_id}")).text)
        ft = token_of((await friend.get(f"/books/{book_id}")).text)
        for i in range(3):
            await read_chunk(host, book_id, i, ht, clock)
        r = await host.post(
            f"/api/v1/books/{book_id}/reactions",
            json={"chunk_index": 2, "anchor": 0, "comment": "범인은 결국 장인이었다"},
            headers={"X-CSRF-Token": ht},
        )
        assert r.status_code == 201

        sealed = (await friend.get(f"/api/v1/books/{book_id}/reactions", params={"chunk": 2})).json()
        assert sealed == {"chunk": 2, "sealed": 1, "items": []}
        assert "범인" not in str(sealed)
        social = (await friend.get(f"/api/v1/books/{book_id}/social")).json()
        assert social["sealed_ahead"] == 1 and social["friends"][0]["nickname"] == "호스트"

        for i in range(3):
            await read_chunk(friend, book_id, i, ft, clock)
        opened = (await friend.get(f"/api/v1/books/{book_id}/reactions", params={"chunk": 2})).json()
        assert opened["sealed"] == 0 and opened["items"][0]["body"] == "범인은 결국 장인이었다"

        # 방에 없는 사람에게는 보이지 않는다
        await signup(stranger, email="s@example.com")
        st = token_of((await stranger.get(f"/books/{book_id}")).text)
        for i in range(3):
            await read_chunk(stranger, book_id, i, st, clock)
        alone = (await stranger.get(f"/api/v1/books/{book_id}/reactions", params={"chunk": 2})).json()
        assert alone["items"] == []


async def test_cannot_react_to_pages_not_reached(api, clock):
    async with api(upstream) as host, api(upstream) as friend:
        book_id = await _race_pair(host, friend)
        ft = token_of((await friend.get(f"/books/{book_id}")).text)
        ahead = await friend.post(
            f"/api/v1/books/{book_id}/reactions",
            json={"chunk_index": 2, "emoji": "😮"},
            headers={"X-CSRF-Token": ft},
        )
        bad = await friend.post(
            f"/api/v1/books/{book_id}/reactions",
            json={"chunk_index": 0, "emoji": "🍕"},
            headers={"X-CSRF-Token": ft},
        )
        ok = await friend.post(
            f"/api/v1/books/{book_id}/reactions",
            json={"chunk_index": 0, "emoji": "😂"},
            headers={"X-CSRF-Token": ft},
        )
    assert ahead.status_code == 422 and bad.status_code == 422 and ok.status_code == 201


# --- GOAL #5: 실시간 진행률 (TestClient는 한 이벤트 루프에서 HTTP와 WebSocket을 함께 돌린다) ---


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    engine_box = {}

    async def _session():
        if "f" not in engine_box:  # TestClient의 루프 안에서 엔진을 만든다
            engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/live.db")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            engine_box["f"] = async_sessionmaker(engine, expire_on_commit=False)
        async with engine_box["f"]() as s:
            yield s

    upstream_client: httpx.AsyncClient = mock_client(upstream)
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_http_client] = lambda: upstream_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _signup_sync(c: TestClient, email: str, nickname: str) -> dict:
    c.cookies.clear()
    token = re.search(r'name="csrf" value="([^"]+)"', c.get("/signup").text).group(1)
    data = {
        "nickname": nickname,
        "email": email,
        "password": "password123",
        "password_confirm": "password123",
        "csrf": token,
    }
    assert c.post("/signup", data=data, follow_redirects=False).status_code == 303
    return dict(c.cookies)


def test_friend_progress_arrives_over_websocket_within_a_second(live_client, monkeypatch):
    import datetime as dt

    from app.services import books as book_service

    now = {"t": dt.datetime.now(dt.UTC)}
    monkeypatch.setattr(book_service, "clock", lambda: now["t"])
    c = live_client

    a = _signup_sync(c, "a@example.com", "에이")
    page = c.get("/races")
    r = c.post(
        "/races/start/wikisource/긴글",
        data={"csrf": token_of(page.text), "days": "7"},
        follow_redirects=False,
    )
    race = c.get(r.headers["location"])
    code = re.search(r'id="code">([A-Z0-9]{6})<', race.text).group(1)
    book_id = re.search(r'href="/books/(\d+)"', race.text).group(1)

    b = _signup_sync(c, "b@example.com", "비")
    c.post(f"/join/{code}", data={"csrf": token_of(c.get(f"/join/{code}").text)}, follow_redirects=False)

    with c.websocket_connect(f"/api/v1/ws/books/{book_id}") as ws:  # B가 접속
        c.cookies.clear()
        c.cookies.update(a)
        token = token_of(c.get(f"/books/{book_id}").text)
        h = {"X-CSRF-Token": token}
        c.put(f"/api/v1/books/{book_id}/progress", json={"chunk_index": 0}, headers=h)
        opened = ws.receive_json()
        assert opened["type"] == "progress.updated" and opened["advanced"] is False
        now["t"] += dt.timedelta(minutes=10)
        started = time.monotonic()
        c.put(f"/api/v1/books/{book_id}/progress", json={"chunk_index": 0, "verified": True}, headers=h)
        msg = ws.receive_json()
        elapsed = time.monotonic() - started
    assert msg == {
        "type": "progress.updated",
        "user_id": msg["user_id"],
        "nickname": "에이",
        "current_chunk": 0,
        "verified_chunk": 0,
        "advanced": True,
    }
    assert elapsed < 1.0
    assert b  # B의 세션으로 연결했음


def test_websocket_rejects_anonymous(live_client):
    c = live_client
    c.cookies.clear()
    with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/api/v1/ws/books/1") as ws:
        ws.receive_json()
    assert e.value.code == 4401


async def test_only_author_can_delete_a_reaction(api, clock):
    async with api(upstream) as host, api(upstream) as friend:
        book_id = await _race_pair(host, friend)
        ht = token_of((await host.get(f"/books/{book_id}")).text)
        ft = token_of((await friend.get(f"/books/{book_id}")).text)
        r = await host.post(
            f"/api/v1/books/{book_id}/reactions",
            json={"chunk_index": 0, "emoji": "😂"},
            headers={"X-CSRF-Token": ht},
        )
        rid = r.json()["id"]
        by_friend = await friend.delete(
            f"/api/v1/books/{book_id}/reactions/{rid}", headers={"X-CSRF-Token": ft}
        )
        no_csrf = await host.delete(f"/api/v1/books/{book_id}/reactions/{rid}")
        by_author = await host.delete(
            f"/api/v1/books/{book_id}/reactions/{rid}", headers={"X-CSRF-Token": ht}
        )
        left = (await host.get(f"/api/v1/books/{book_id}/reactions", params={"chunk": 0})).json()
    assert by_friend.status_code == 404 and no_csrf.status_code == 403
    assert by_author.status_code == 204 and left["items"] == []
