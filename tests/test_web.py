"""웹 화면: 첫 화면(앱 안내) · 로그인/가입 폼 · 초대 미리보기만 남아 있다. 나머지는 mobile/ 앱과 JSON API."""

import re
from datetime import timedelta

from sqlalchemy import update

from app.core.clock import utcnow
from app.models import Room
from tests.conftest import make_book, signup
from tests.test_reading import CHUNK

HTML = {"accept": "text/html"}


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


async def web_signup(c, nickname: str, next_path: str = "/") -> str:
    """가입 폼으로 가입하고, 리다이렉트된 위치를 돌려준다."""
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
    return r.headers["location"]


async def web_login(c, email: str, password: str = "password123", next_path: str | None = None):
    page = await c.get("/login", headers=HTML)
    data = {"email": email, "password": password, "csrf_token": csrf_of(page.text)}
    if next_path is not None:
        data["next"] = next_path
    return await c.post("/login", data=data)


async def make_room(api, session_factory, name: str = "같이 읽어요") -> tuple[str, int]:
    """API로 방을 만든다(방장 '서연'). (초대 코드, 방 id)."""
    book = await make_book(session_factory, [CHUNK], title="봄봄")
    owner = api()
    await signup(owner, "서연")
    room = (await owner.post("/api/v1/rooms", json={"book_id": book, "name": name})).json()
    return room["invite_code"], room["id"]


# ── 첫 화면 ──────────────────────────────────────────────


async def test_landing_signed_out(api):
    async with api() as c:
        r = await c.get("/", headers=HTML)
    assert r.status_code == 200
    for needle in (
        "함께읽기",
        "앱에서 열어 주세요",
        "초대 링크 미리보기와 계정 만들기만 해요",
        'href="/login"',
        'href="/signup"',
    ):
        assert needle in r.text, needle
    assert "로그인됨" not in r.text and 'action="/logout"' not in r.text


async def test_landing_signed_in_then_logout(api):
    async with api() as c:
        assert await web_signup(c, "서연") == "/"
        page = await c.get("/", headers=HTML)
        assert "환영해요, 서연님!" in page.text  # 가입 직후 안내
        assert "로그인됨 · 서연" in page.text and 'action="/logout"' in page.text
        assert 'href="/signup"' not in page.text
        r = await c.post("/logout", data={"csrf_token": csrf_of(page.text)})
        assert r.status_code == 303 and r.headers["location"] == "/"
        page = await c.get("/", headers=HTML)
        assert "로그인됨" not in page.text and 'href="/login"' in page.text


async def test_removed_web_pages_are_gone(api):
    async with api() as c:
        await web_signup(c, "길잃음")
        for path in ("/rooms", "/search", "/teams", "/me", "/books/1", "/books/1/read", "/sw.js", "/offline"):
            r = await c.get(path, headers=HTML)
            assert r.status_code == 404, path
        assert (await c.get("/manifest.webmanifest")).status_code == 404
        assert (await c.get("/static/js/reader.js")).status_code == 404
        assert (await c.get("/static/css/glass.css")).status_code == 200
        assert (await c.get("/static/icons/icon-192.png")).status_code == 200


# ── 로그인 · 가입 ─────────────────────────────────────────


async def test_auth_pages_render_and_csrf_is_enforced(api):
    async with api() as c:
        assert (await c.get("/login", headers=HTML)).status_code == 200
        assert (await c.get("/signup", headers=HTML)).status_code == 200
        # 토큰 없는(또는 틀린) 폼 전송은 거절
        assert (await c.post("/login", data={"email": "a@b.kr", "password": "x"})).status_code == 403
        bad = {
            "nickname": "a",
            "email": "a@b.kr",
            "password": "x",
            "password_confirm": "x",
            "csrf_token": "nope",
        }
        assert (await c.post("/signup", data=bad)).status_code == 403
        assert (await c.post("/logout")).status_code == 403


async def test_signup_redirects_home_and_rejects_unsafe_next(api):
    async with api() as c:
        assert await web_signup(c, "준호", "//evil.example/x") == "/"
    async with api() as c:
        assert await web_signup(c, "민지", "https://evil.example") == "/"


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


async def test_login_redirects_home_or_safe_next(api):
    async with api() as c:
        await web_signup(c, "서연")
    email = f"{'서연'.encode().hex()}@web.kr"
    async with api() as c:
        r = await web_login(c, email)
        assert r.status_code == 303 and r.headers["location"] == "/"
        # 이미 로그인했으면 로그인 화면은 다음 위치로 보낸다
        r = await c.get("/login?next=/r/abcd1234", headers=HTML)
        assert r.status_code == 303 and r.headers["location"] == "/r/abcd1234"
    async with api() as c:
        r = await web_login(c, email, next_path="/r/abcd1234")
        assert r.headers["location"] == "/r/abcd1234"
    async with api() as c:
        r = await web_login(c, email, next_path="//evil.example")
        assert r.headers["location"] == "/"
    async with api() as c:
        r = await web_login(c, email, password="wrong-password")
        assert r.status_code == 200 and "이메일 또는 비밀번호가 맞지 않아요" in r.text


# ── 초대 미리보기 ─────────────────────────────────────────


async def test_invite_preview_shows_code_and_app_steps(api, session_factory):
    code, _ = await make_room(api, session_factory)
    async with api() as friend:
        r = await friend.get(f"/r/{code}", headers=HTML)
        assert r.status_code == 200
        assert "같이 읽어요" in r.text and "봄봄" in r.text and "서연" in r.text
        assert f'<div class="code" id="invite-code">{code}</div>' in r.text
        assert "초대 코드로 들어가기" in r.text and "코드 복사하기" in r.text
        # 사라진 웹 방 화면이나 웹 참여 폼으로 보내지 않는다
        assert "/rooms/" not in r.text and f"/r/{code}/join" not in r.text
        # 가입하면 같은 미리보기로 돌아온다
        assert f"/signup?next=/r/{code}" in r.text
        assert await web_signup(friend, "준호", f"/r/{code}") == f"/r/{code}"
        r = await friend.get(f"/r/{code}", headers=HTML)
        assert "로그인됨 · 준호" in r.text and code in r.text
        assert (await friend.post(f"/r/{code}/join", data={"csrf_token": csrf_of(r.text)})).status_code in (
            404,
            405,
        )


async def test_invite_preview_for_member_and_expired(api, session_factory):
    code, room_id = await make_room(api, session_factory)
    async with api() as friend:
        await signup(friend, "준호")
        assert (await friend.post(f"/api/v1/invites/{code}/join")).status_code == 200
        r = await friend.get(f"/r/{code}", headers=HTML)
        assert r.status_code == 200 and "이미 이 방에 들어와 있어요" in r.text
    async with session_factory() as s:
        await s.execute(
            update(Room).where(Room.id == room_id).values(invite_expires_at=utcnow() - timedelta(days=1))
        )
        await s.commit()
    async with api() as c:
        r = await c.get(f"/r/{code}", headers=HTML)
        assert r.status_code == 200 and "초대 링크가 만료됐어요" in r.text
        assert 'id="invite-code"' not in r.text


async def test_invite_preview_bad_code_is_404_page(api):
    async with api() as c:
        r = await c.get("/r/nope0000", headers=HTML)
    assert r.status_code == 404
    assert "초대 링크를 찾을 수 없어요" in r.text and "<html" in r.text
