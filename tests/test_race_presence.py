"""대결방: 함께 읽는 중(presence), 문장 공유 피드, 레이스 바."""

import datetime as dt
import re

from app.services import races as race_service
from tests.conftest import read_chunk, signup
from tests.test_api import upstream


def csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


async def _race_pair(host, friend):
    """호스트가 대결을 만들고 친구가 참가한다. (방 id, 책 id, 호스트 토큰, 친구 토큰)."""
    await signup(host, email="host@example.com", nickname="호스트")
    await signup(friend, email="friend@example.com", nickname="친구")
    page = await host.get("/races")
    r = await host.post("/races/start/wikisource/긴글", data={"csrf": csrf(page.text), "days": "3"})
    race_url = r.headers["location"]
    room_id = int(race_url.rsplit("/", 1)[1])
    race = await host.get(race_url)
    code = re.search(r'id="code">([A-Z0-9]{6})<', race.text).group(1)
    preview = await friend.get(f"/join/{code}")
    await friend.post(f"/join/{code}", data={"csrf": csrf(preview.text)})
    book_id = int(re.search(r'href="/books/(\d+)"', race.text).group(1))
    tokens = []
    for c in (host, friend):
        reader = await c.get(f"/books/{book_id}")
        tokens.append(reader.text.split('data-csrf="')[1].split('"')[0])
    return room_id, book_id, *tokens


async def test_presence_shows_friend_page_and_expires(api, monkeypatch):
    now = {"t": dt.datetime.now(dt.UTC)}
    monkeypatch.setattr(race_service, "clock", lambda: now["t"])
    async with api(upstream) as host, api(upstream) as friend:
        room_id, book_id, ht, ft = await _race_pair(host, friend)
        r = await friend.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 2}, headers={"X-CSRF-Token": ft}
        )
        assert r.status_code == 200 and r.json()["rooms"][0]["id"] == room_id
        assert r.json()["friends"] == []  # 호스트는 아직 안 들어왔다

        mine = await host.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 0}, headers={"X-CSRF-Token": ht}
        )
        friends = mine.json()["friends"]
        assert [(f["nickname"], f["chunk"]) for f in friends] == [("친구", 2)]

        board = (await host.get(f"/api/v1/races/{room_id}/presence")).json()["present"]
        assert {p["nickname"] for p in board} == {"호스트", "친구"}

        now["t"] += dt.timedelta(seconds=45)  # 친구가 창을 닫은 지 오래됐다
        await host.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 1}, headers={"X-CSRF-Token": ht}
        )
        board = (await host.get(f"/api/v1/races/{room_id}/presence")).json()["present"]
        assert [p["nickname"] for p in board] == ["호스트"]


async def test_presence_requires_csrf_and_clamps_page(api):
    async with api(upstream) as host, api(upstream) as friend:
        room_id, book_id, ht, ft = await _race_pair(host, friend)
        bad = await host.put(f"/api/v1/books/{book_id}/presence", json={"chunk_index": 0})
        assert bad.status_code == 403
        await friend.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 9999}, headers={"X-CSRF-Token": ft}
        )
        board = (await host.get(f"/api/v1/races/{room_id}/presence")).json()["present"]
    assert board[0]["chunk"] < 9999


async def test_race_endpoints_hidden_from_non_members(api):
    async with api(upstream) as host, api(upstream) as friend, api(upstream) as stranger:
        room_id, *_ = await _race_pair(host, friend)
        await signup(stranger, email="s@example.com", nickname="남")
        home = await stranger.get("/")
        token = re.search(r'<meta name="csrf" content="([^"]+)"', home.text).group(1)
        assert (await stranger.get(f"/api/v1/races/{room_id}/presence")).status_code == 404
        assert (await stranger.get(f"/api/v1/races/{room_id}/quotes")).status_code == 404
        r = await stranger.post(
            f"/api/v1/races/{room_id}/quotes",
            json={"chunk_index": 0, "text": "몰래"},
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 404
    async with api(upstream) as anon:
        assert (await anon.get(f"/api/v1/races/{room_id}/quotes")).status_code in (401, 403)


async def test_quote_feed_with_spoiler_guard(api, clock):
    async with api(upstream) as host, api(upstream) as friend:
        room_id, book_id, ht, ft = await _race_pair(host, friend)
        for i in range(2):
            await read_chunk(friend, book_id, i, ft, clock)
        h = {"X-CSRF-Token": ft}
        ok = await friend.post(
            f"/api/v1/races/{room_id}/quotes", json={"chunk_index": 0, "text": "  첫  문장이에요 "}, headers=h
        )
        assert ok.status_code == 201 and ok.json()["text"] == "첫 문장이에요"
        await friend.post(f"/api/v1/races/{room_id}/quotes", json={"chunk_index": 2, "text": "뒤쪽 문장"}, headers=h)
        ahead = await friend.post(
            f"/api/v1/races/{room_id}/quotes", json={"chunk_index": 5, "text": "안 읽은 쪽"}, headers=h
        )
        assert ahead.status_code == 422
        empty = await friend.post(f"/api/v1/races/{room_id}/quotes", json={"chunk_index": 0, "text": "  "}, headers=h)
        assert empty.status_code == 422

        # 호스트는 0쪽만 읽었다: 2쪽 문장은 봉인
        await read_chunk(host, book_id, 0, ht, clock)
        feed = (await host.get(f"/api/v1/races/{room_id}/quotes")).json()["items"]
        assert [(q["chunk"], q["text"], q["sealed"]) for q in feed] == [(2, None, True), (0, "첫 문장이에요", False)]
        own = (await friend.get(f"/api/v1/races/{room_id}/quotes")).json()["items"]
        assert all(not q["sealed"] for q in own)


async def test_race_page_has_track_and_feed(api):
    async with api(upstream) as host, api(upstream) as friend:
        room_id, book_id, *_ = await _race_pair(host, friend)
        page = (await host.get(f"/races/{room_id}")).text
        reader = (await host.get(f"/books/{book_id}")).text
    assert 'id="raceTrack"' in page and 'id="quotes"' in page
    assert page.count('<div class="rc-lane') == 2
    assert reader.count('src="/static/presence.js"') == 1
