"""대결방: 함께 읽는 중(presence), 문장 공유 피드, 레이스 바."""

import datetime as dt
import re

from app.services import books as book_service
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
    monkeypatch.setattr(book_service, "clock", lambda: now["t"])
    async with api(upstream) as host, api(upstream) as friend:
        room_id, book_id, ht, ft = await _race_pair(host, friend)
        now["t"] += dt.timedelta(seconds=61)  # 리더를 펼친 흔적이 식었다
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
        await friend.post(
            f"/api/v1/races/{room_id}/quotes", json={"chunk_index": 2, "text": "뒤쪽 문장"}, headers=h
        )
        ahead = await friend.post(
            f"/api/v1/races/{room_id}/quotes", json={"chunk_index": 5, "text": "안 읽은 쪽"}, headers=h
        )
        assert ahead.status_code == 422
        empty = await friend.post(
            f"/api/v1/races/{room_id}/quotes", json={"chunk_index": 0, "text": "  "}, headers=h
        )
        assert empty.status_code == 422

        # 호스트는 0쪽만 읽었다: 2쪽 문장은 봉인
        await read_chunk(host, book_id, 0, ht, clock)
        feed = (await host.get(f"/api/v1/races/{room_id}/quotes")).json()["items"]
        assert [(q["chunk"], q["text"], q["sealed"]) for q in feed] == [
            (2, None, True),
            (0, "첫 문장이에요", False),
        ]
        own = (await friend.get(f"/api/v1/races/{room_id}/quotes")).json()["items"]
        assert all(not q["sealed"] for q in own)


async def test_race_page_has_track_and_feed(api):
    async with api(upstream) as host, api(upstream) as friend:
        room_id, book_id, *_ = await _race_pair(host, friend)
        page = (await host.get(f"/races/{room_id}")).text
        reader = (await host.get(f"/books/{book_id}")).text
    assert 'id="raceTrack"' in page and 'id="quotes"' in page
    assert page.count('<div class="lane') == 2
    assert reader.count('src="/static/presence.js"') == 1


async def _open_book(c, page: str) -> tuple[int, str]:
    url = (await c.get(f"/open/wikisource/{page}")).headers["location"]
    token = (await c.get(url)).text.split('data-csrf="')[1].split('"')[0]
    return int(url.rsplit("/", 1)[1]), token


async def test_presence_covers_friends_outside_a_race_room_and_expires_at_60s(api, monkeypatch):
    """대결방은 다른 책인데 같은 책을 펼친 친구도 보인다. 모르는 사람은 안 보인다. 60초가 지나면 빠진다."""
    now = {"t": dt.datetime.now(dt.UTC)}
    monkeypatch.setattr(race_service, "clock", lambda: now["t"])
    monkeypatch.setattr(book_service, "clock", lambda: now["t"])
    async with api(upstream) as host, api(upstream) as friend, api(upstream) as stranger:
        await _race_pair(host, friend)  # '긴글'로 맺은 친구
        await signup(stranger, email="s@example.com", nickname="남")
        book_id, ht = await _open_book(host, "봄봄")  # 대결방 없는 다른 책
        _, ft = await _open_book(friend, "봄봄")
        _, st = await _open_book(stranger, "봄봄")
        await friend.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 0}, headers={"X-CSRF-Token": ft}
        )
        await stranger.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 0}, headers={"X-CSRF-Token": st}
        )
        r = await host.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 0}, headers={"X-CSRF-Token": ht}
        )
        body = r.json()
        assert body["rooms"] == [] and body["ttl"] == 60
        assert [(f["nickname"], f["chunk"], f["verified_chunk"]) for f in body["friends"]] == [
            ("친구", 0, -1)
        ]

        now["t"] += dt.timedelta(seconds=50)  # 아직 60초 안
        r = await host.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 0}, headers={"X-CSRF-Token": ht}
        )
        assert [f["nickname"] for f in r.json()["friends"]] == ["친구"]

        now["t"] += dt.timedelta(seconds=15)  # 친구는 65초째 소식이 없다
        r = await host.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 0}, headers={"X-CSRF-Token": ht}
        )
        assert r.json()["friends"] == []

        # 친구가 다시 박동하면 바로 돌아온다 — 쪽도 함께
        await friend.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 9999}, headers={"X-CSRF-Token": ft}
        )
        r = await host.put(
            f"/api/v1/books/{book_id}/presence", json={"chunk_index": 0}, headers={"X-CSRF-Token": ht}
        )
        [f] = r.json()["friends"]
        assert f["nickname"] == "친구" and 0 <= f["chunk"] < 9999


async def test_reader_has_dwell_ring_and_whole_book_track(api):
    async with api(upstream) as c:
        await signup(c)
        book_id, _ = await _open_book(c, "긴글")
        html = (await c.get(f"/books/{book_id}")).text
        js = (await c.get("/static/presence.js")).text
    for el in ('id="ring"', 'id="ringNum"', 'id="track"', 'id="fill"', 'id="marks"', 'id="left"'):
        assert el in html
    assert "const BEAT = 5000" in js and "haedok:presence" in js and "window.colorFor" in js
    # 친구 색은 대결 화면과 같은 palette.js에서 — presence.js보다 먼저 불러야 한다
    assert html.index("/static/palette.js") < html.index("/static/presence.js")
