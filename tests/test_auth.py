import time

from app import auth
from tests.conftest import csrf_of, signup
from tests.test_api import upstream


def form(**kw):
    base = {
        "nickname": "독자",
        "email": "a@b.co",
        "password": "password123",
        "password_confirm": "password123",
    }
    return auth.SignupForm(**(base | kw))


def test_signup_validation_rules():
    assert form().validate()
    f = form(email="  Reader@Example.COM ")
    assert f.validate() and f.email == "reader@example.com"
    assert "password" in (f := form(password="short", password_confirm="short"), f.validate(), f.errors)[2]
    assert (
        "password" in (f := form(password="가" * 25, password_confirm="가" * 25), f.validate(), f.errors)[2]
    )  # 75바이트
    assert "password_confirm" in (f := form(password_confirm="different1"), f.validate(), f.errors)[2]
    assert "email" in (f := form(email="nope"), f.validate(), f.errors)[2]


def test_password_hash_roundtrip():
    h = auth.hash_password("password123")
    assert h.startswith("$2b$12$")
    assert auth.verify_password("password123", h)
    assert not auth.verify_password("password124", h)
    assert not auth.verify_password("x", None)


async def test_duplicate_email_is_rejected_case_insensitively(api):
    async with api(upstream) as c, api(upstream) as other:
        await signup(c, email="dup@example.com")
        token = await csrf_of(other)
        r = await other.post(
            "/signup",
            data={
                "nickname": "둘째",
                "email": "DUP@example.com",
                "password": "password123",
                "password_confirm": "password123",
                "csrf": token,
            },
        )
    assert r.status_code == 200 and "이미 가입된 이메일" in r.text
    assert "password123" not in r.text  # 비밀번호를 다시 출력하지 않는다


async def test_login_logout_and_wrong_password(api):
    async with api(upstream) as c:
        await signup(c, email="me@example.com")
        c.cookies.clear()
        token = await csrf_of(c, "/login")
        bad = await c.post(
            "/login", data={"email": "me@example.com", "password": "wrongpass1", "csrf": token}
        )
        ok = await c.post(
            "/login",
            data={"email": " ME@example.com", "password": "password123", "next": "/library", "csrf": token},
        )
    assert bad.status_code == 200 and "맞지 않아요" in bad.text
    assert ok.status_code == 303 and ok.headers["location"] == "/library"


async def test_login_rejects_offsite_next(api):
    async with api(upstream) as c:
        await signup(c, email="me@example.com")
        c.cookies.clear()
        token = await csrf_of(c, "/login")
        r = await c.post(
            "/login",
            data={
                "email": "me@example.com",
                "password": "password123",
                "next": "//evil.example",
                "csrf": token,
            },
        )
    assert r.headers["location"] == "/"


async def test_post_without_csrf_is_forbidden(api):
    async with api(upstream) as c:
        r = await c.post(
            "/signup",
            data={
                "nickname": "a",
                "email": "x@y.z",
                "password": "password123",
                "password_confirm": "password123",
            },
        )
    assert r.status_code == 403


async def test_session_expires_after_idle(api, monkeypatch):
    async with api(upstream) as c:
        await signup(c)
        assert (await c.get("/me")).status_code == 200
        real = time.time
        monkeypatch.setattr(auth.time, "time", lambda: real() + 31 * 60)
        r = await c.get("/me")
    assert r.status_code == 303
