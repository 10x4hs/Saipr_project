"""웹 화면: 모든 페이지가 렌더링되고, 폼 흐름(가입 → 방 만들기 → 초대 → 입장)이 동작한다."""

import re

from tests.conftest import make_book
from tests.test_reading import CHUNK

HTML = {"accept": "text/html"}


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


async def web_signup(c, nickname: str, next_path: str = "/") -> None:
    page = await c.get(f"/signup?next={next_path}", headers=HTML)
    r = await c.post(
        "/signup",
        data={
            "nickname": nickname,
            "email": f"{nickname.encode().hex()}@web.kr",
            "password": "password123",
            "password_confirm": "password123",
            "next": next_path,
            "csrf_token": csrf_of(page.text),
        },
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == next_path


async def test_pages_require_login(api):
    async with api() as c:
        r = await c.get("/", headers=HTML)
        assert r.status_code == 303 and r.headers["location"] == "/login?next=/"
        assert (await c.get("/login", headers=HTML)).status_code == 200
        assert (await c.get("/signup", headers=HTML)).status_code == 200
        # 토큰 없는 폼 전송은 거절
        assert (await c.post("/login", data={"email": "a@b.kr", "password": "x"})).status_code == 403


async def test_signup_form_errors_do_not_echo_password(api):
    async with api() as c:
        page = await c.get("/signup", headers=HTML)
        r = await c.post(
            "/signup",
            data={
                "nickname": "a",
                "email": "bad",
                "password": "secret-pw-1",
                "password_confirm": "x",
                "csrf_token": csrf_of(page.text),
            },
        )
        assert r.status_code == 200
        assert "이메일 형식" in r.text and "secret-pw-1" not in r.text


async def test_full_web_flow(api, session_factory):
    book = await make_book(session_factory, [CHUNK, CHUNK], title="봄봄")
    owner, friend = api(), api()
    await web_signup(owner, "서연")

    home = await owner.get("/", headers=HTML)
    assert home.status_code == 200 and "오늘도" in home.text
    token = csrf_of(home.text)

    detail = await owner.get(f"/books/{book}", headers=HTML)
    assert "읽기 시작" in detail.text
    r = await owner.post(
        "/rooms", data={"book_id": book, "name": "같이 읽어요", "mode": "async", "csrf_token": token}
    )
    assert r.status_code == 303
    room_url = r.headers["location"]
    room_page = await owner.get(room_url, headers=HTML)
    assert room_page.status_code == 200
    code = re.search(r"/r/([\w-]{8})", room_page.text).group(1)

    # 비로그인 친구: 미리보기 → 가입 → 같은 초대 링크로 복귀 → 참여
    preview = await friend.get(f"/r/{code}", headers=HTML)
    assert (
        preview.status_code == 200 and "같이 읽어요" in preview.text and "로그인하고 참여하기" in preview.text
    )
    await web_signup(friend, "준호", f"/r/{code}")
    preview = await friend.get(f"/r/{code}", headers=HTML)
    r = await friend.post(f"/r/{code}/join", data={"csrf_token": csrf_of(preview.text)})
    assert r.status_code == 303 and r.headers["location"] == room_url
    room_page = await friend.get(room_url, headers=HTML)
    assert "서연" in room_page.text and ">나<" in room_page.text  # 내 줄은 시안처럼 "나"

    reader = await friend.get(f"/books/{book}/read", headers=HTML)
    assert reader.status_code == 200 and 'id="reader-root"' in reader.text
    chunk = (await friend.get(f"/books/{book}/chunk/0")).json()
    assert chunk["paragraphs"] == CHUNK and chunk["min_dwell_ms"] == 60_000

    for path in ("/search?q=봄봄", "/teams", "/me", f"/books/{book}"):
        assert (await friend.get(path, headers=HTML)).status_code == 200, path


async def test_team_and_battle_pages(api, session_factory):
    book = await make_book(session_factory, [CHUNK])
    a, b = api(), api()
    await web_signup(a, "가팀장")
    await web_signup(b, "나팀장")
    t = csrf_of((await a.get("/teams", headers=HTML)).text)
    r = await a.post("/teams", data={"name": "가팀", "csrf_token": t})
    team_a = r.headers["location"]
    tb = csrf_of((await b.get("/teams", headers=HTML)).text)
    team_b = (await b.post("/teams", data={"name": "나팀", "csrf_token": tb})).headers["location"]
    # 배틀은 두 팀 모두 2명 이상이어야 한다
    for team_url, owner, nick in ((team_a, a, "가팀원"), (team_b, b, "나팀원")):
        code = re.search(
            r"초대 코드 <strong>([\w-]+)</strong>", (await owner.get(team_url, headers=HTML)).text
        ).group(1)
        member = api()
        await web_signup(member, nick)
        page = await member.get("/teams", headers=HTML)
        r = await member.post("/teams/join", data={"code": code, "csrf_token": csrf_of(page.text)})
        assert r.headers["location"] == team_url

    page = await a.get(f"/books/{book}", headers=HTML)
    await a.post(f"/library/{book}/shelf", data={"shelf": "reading", "csrf_token": csrf_of(page.text)})
    page = await a.get(team_a, headers=HTML)
    assert "다른 팀에 도전하기" in page.text
    r = await a.post(
        "/battles",
        data={
            "type": "page_race",
            "book_id": book,
            "team_a_id": team_a.rsplit("/", 1)[1],
            "team_b_id": team_b.rsplit("/", 1)[1],
            "days": 7,
            "csrf_token": csrf_of(page.text),
        },
    )
    assert r.status_code == 303
    battle = await a.get(r.headers["location"], headers=HTML)
    assert battle.status_code == 200 and "가팀" in battle.text and "나팀" in battle.text


async def test_service_error_flashes_and_redirects(api, session_factory):
    book = await make_book(session_factory, [CHUNK])
    async with api() as c:
        await web_signup(c, "에러")
        page = await c.get(f"/books/{book}", headers=HTML)
        r = await c.post(
            f"/library/{book}/progress",
            data={"progress_pct": "50", "csrf_token": csrf_of(page.text)},
            headers={"referer": f"http://test/books/{book}"},
        )
        assert r.status_code == 303 and r.headers["location"] == f"/books/{book}"
        page = await c.get(f"/books/{book}", headers=HTML)
        assert "직접 입력할 수 없어요" in page.text


async def test_not_found_page(api):
    async with api() as c:
        await web_signup(c, "길잃음")
        r = await c.get("/books/999", headers=HTML)
        assert r.status_code == 404 and "책을 찾을 수 없어요" in r.text
        assert (await c.get("/r/nope0000", headers=HTML)).status_code == 404
