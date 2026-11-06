"""가입 이메일 인증: 코드 확인 전엔 계정이 없고, 10분·5번·60초 규칙을 지킨다."""

import json
import logging
import time

import httpx
from sqlalchemy import func, select

from app import auth
from app.core.config import get_settings
from app.models import SignupVerification, User
from tests.conftest import REAL_SEND_SIGNUP_CODE, SENT_CODES, csrf_of, mock_client
from tests.test_api import upstream

EMAIL = "new@example.com"


async def start(c: httpx.AsyncClient) -> str:
    token = await csrf_of(c)
    r = await c.post(
        "/signup",
        data={
            "nickname": "새독자",
            "email": EMAIL,
            "password": "password123",
            "password_confirm": "password123",
            "csrf": token,
        },
    )
    assert r.status_code == 303 and r.headers["location"] == "/signup/verify"
    return token


async def users(session_factory) -> int:
    async with session_factory() as s:
        return await s.scalar(select(func.count(User.id)))


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def shift_clock(monkeypatch, seconds: float) -> None:
    real = time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + seconds)


async def test_account_is_created_only_after_code(api, session_factory):
    async with api(upstream) as c:
        token = await start(c)
        assert await users(session_factory) == 0
        page = await c.get("/signup/verify")
        assert EMAIL in page.text and "6자리" in page.text
        assert (await c.get("/me")).status_code == 303  # 아직 로그인 아님
        r = await c.post("/signup/verify", data={"code": SENT_CODES[EMAIL], "csrf": token})
        assert r.status_code == 303 and r.headers["location"] == "/"
        assert (await c.get("/me")).status_code == 200
    assert await users(session_factory) == 1
    async with session_factory() as s:
        assert await s.scalar(select(func.count(SignupVerification.id))) == 0


async def test_code_is_six_digits_and_not_stored_raw(api, session_factory):
    async with api(upstream) as c:
        await start(c)
    code = SENT_CODES[EMAIL]
    assert len(code) == 6 and code.isdigit()
    async with session_factory() as s:
        row = await s.scalar(select(SignupVerification))
    assert code not in row.code_hash and row.expires_at - row.sent_at == auth.CODE_TTL_S


async def test_five_wrong_attempts_lock_the_code(api, session_factory):
    async with api(upstream) as c:
        token = await start(c)
        code = SENT_CODES[EMAIL]
        for left in (4, 3, 2, 1):
            r = await c.post("/signup/verify", data={"code": wrong(code), "csrf": token})
            assert r.status_code == 200 and f"남은 기회 {left}번" in r.text
        r = await c.post("/signup/verify", data={"code": wrong(code), "csrf": token})
        assert "너무 많이 틀렸어요" in r.text
        r = await c.post("/signup/verify", data={"code": code, "csrf": token})
        assert r.status_code == 200 and "너무 많이 틀렸어요" in r.text
    assert await users(session_factory) == 0


async def test_code_expires_after_ten_minutes(api, session_factory, monkeypatch):
    async with api(upstream) as c:
        token = await start(c)
        shift_clock(monkeypatch, auth.CODE_TTL_S + 1)
        r = await c.post("/signup/verify", data={"code": SENT_CODES[EMAIL], "csrf": token})
    assert r.status_code == 200 and "만료" in r.text
    assert await users(session_factory) == 0


async def test_resend_has_cooldown_and_replaces_code(api, session_factory, monkeypatch):
    async with api(upstream) as c:
        token = await start(c)
        first = SENT_CODES[EMAIL]
        r = await c.post("/signup/resend", data={"csrf": token})
        assert "초 뒤에 다시" in r.text and SENT_CODES[EMAIL] == first
        # 같은 이메일로 가입을 다시 눌러도 간격 안에서는 새 메일이 나가지 않는다
        SENT_CODES.clear()
        await start(c)
        assert EMAIL not in SENT_CODES
        shift_clock(monkeypatch, auth.RESEND_COOLDOWN_S + 1)
        r = await c.post("/signup/resend", data={"csrf": token})
        assert "새 코드를 보냈어요" in r.text
        second = SENT_CODES[EMAIL]
        if second != first:  # 백만분의 일 확률로 같은 코드가 나올 수 있다
            r = await c.post("/signup/verify", data={"code": first, "csrf": token})
            assert "맞지 않아요" in r.text
        r = await c.post("/signup/verify", data={"code": second, "csrf": token})
        assert r.status_code == 303
    assert await users(session_factory) == 1


async def test_verify_without_pending_signup_goes_back(api):
    async with api(upstream) as c:
        r = await c.get("/signup/verify")
        assert r.status_code == 303 and r.headers["location"] == "/signup"
        token = await csrf_of(c)
        r = await c.post("/signup/verify", data={"code": "123456", "csrf": token})
        assert r.status_code == 303 and r.headers["location"] == "/signup"


async def test_verify_requires_csrf(api):
    async with api(upstream) as c:
        await start(c)
        r = await c.post("/signup/verify", data={"code": SENT_CODES[EMAIL]})
    assert r.status_code == 403


async def test_signup_form_labels(api):
    async with api(upstream) as c:
        html = (await c.get("/signup")).text
    assert "비밀번호 확인" in html and "한 번 더" not in html


async def test_mail_logs_code_without_api_key(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "resend_api_key", None)
    calls = []
    client = mock_client(lambda req: calls.append(req) or httpx.Response(200))
    with caplog.at_level(logging.WARNING, logger="haedok.mail"):
        assert await REAL_SEND_SIGNUP_CODE(client, "a@b.co", "123456")
    assert "123456" in caplog.text and not calls


async def test_mail_posts_to_resend(monkeypatch):
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_test")
    monkeypatch.setattr(get_settings(), "resend_from", "해독 <no-reply@example.com>")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": "x"})

    assert await REAL_SEND_SIGNUP_CODE(mock_client(handler), "a@b.co", "654321")
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.resend.com/emails"
    assert req.headers["authorization"] == "Bearer re_test"
    assert body["to"] == ["a@b.co"] and "654321" in body["text"]
    assert body["from"] == "해독 <no-reply@example.com>"

    failing = mock_client(lambda req: httpx.Response(422, json={"message": "bad"}))
    assert not await REAL_SEND_SIGNUP_CODE(failing, "a@b.co", "654321")
