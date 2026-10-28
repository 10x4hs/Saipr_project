import re

from tests.conftest import read_chunk, signup
from tests.test_api import upstream


def csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


async def test_race_invite_join_and_leaderboard(api, clock):
    async with api(upstream) as host, api(upstream) as friend:
        await signup(host, email="host@example.com", nickname="호스트")
        await signup(friend, email="friend@example.com", nickname="친구")
        page = await host.get("/races")
        r = await host.post("/races/start/wikisource/긴글", data={"csrf": csrf(page.text), "days": "3"})
        assert r.status_code == 303
        race_url = r.headers["location"]
        race = await host.get(race_url)
        code = re.search(r'id="code">([A-Z0-9]{6})<', race.text).group(1)

        stranger_view = await friend.get(race_url)
        assert stranger_view.status_code == 404  # 참가 전에는 볼 수 없다

        preview = await friend.get(f"/join/{code.lower()}")
        assert preview.status_code == 200 and "호스트님의 초대" in preview.text
        joined = await friend.post(f"/join/{code}", data={"csrf": csrf(preview.text)})
        assert joined.headers["location"] == race_url

        # 친구가 한 쪽을 검증받으면 순위에 반영된다
        book_id = re.search(r'href="/books/(\d+)"', race.text).group(1)
        reader = await friend.get(f"/books/{book_id}")
        token = reader.text.split('data-csrf="')[1].split('"')[0]
        await read_chunk(friend, book_id, 0, token, clock)
        board = (await host.get(race_url)).text
    names = re.findall(r'<div class="who"><b>([^<]+?)\s*(?:<em>|</b>)', board)
    assert names == ["친구", "호스트"]  # 검증된 쪽이 많은 친구가 1위
    assert "1쪽" in board


async def test_unknown_code_returns_to_races_with_error(api):
    async with api(upstream) as c:
        await signup(c)
        r = await c.get("/join/ZZZZZZ")
    assert r.status_code == 303 and "/races?error=" in r.headers["location"]


async def test_cannot_race_with_uploaded_book(api):
    async with api(upstream) as c:
        await signup(c)
        page = await c.get("/upload")
        up = await c.post(
            "/upload",
            files={"file": ("나만.txt", ("가나다라 " * 40).encode(), "text/plain")},
            data={"csrf": csrf(page.text)},
        )
        book_id = up.headers["location"].rsplit("/", 1)[1]
        r = await c.post("/races", data={"csrf": csrf(page.text), "book_id": book_id, "days": "7"})
    assert r.status_code == 400


async def test_settings_saved_to_account_and_validated(api):
    async with api(upstream) as c:
        await signup(c)
        home = await c.get("/")
        token = re.search(r'<meta name="csrf" content="([^"]+)"', home.text).group(1)
        r = await c.put(
            "/api/v1/me/settings",
            json={"mode": "dark", "bg": "aurora", "accent": "teal"},
            headers={"X-CSRF-Token": token},
        )
        bad = await c.put("/api/v1/me/settings", json={"bg": "nope"}, headers={"X-CSRF-Token": token})
        page = await c.get("/me")
    assert r.json()["bg"] == "aurora" and bad.json()["bg"] == "plain"
    assert 'data-theme="dark"' in page.text and 'data-accent="teal"' in page.text


async def test_home_has_3d_popular_with_famous_first(api):
    async with api(upstream) as c:
        await signup(c)
        r = await c.get("/")
    assert 'class="drum-book"' in r.text
    assert r.text.index('data-title="운수 좋은 날"') < r.text.index('data-title="봄봄"')
