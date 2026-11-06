import httpx

from app.core.config import get_settings
from app.services import mail
from app.services.mail import (
    send_signup_code as real_send,  # conftest가 발송 함수를 가짜로 바꾸기 전에 잡아 둔다
)


async def test_smtp_used_when_configured(monkeypatch):
    sent = {}
    monkeypatch.setenv("SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pass")
    get_settings.cache_clear()
    monkeypatch.setattr(mail, "_send_smtp", lambda s, to, subj, text, html: sent.update(to=to, subj=subj))
    async with httpx.AsyncClient() as c:
        assert await real_send(c, "a@b.com", "123456")
    assert sent == {"to": "a@b.com", "subj": "[해독] 가입 인증 코드 123456"}
    get_settings.cache_clear()


async def test_smtp_failure_returns_false(monkeypatch):
    import smtplib

    monkeypatch.setenv("SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "bad")
    get_settings.cache_clear()

    def boom(*a):
        raise smtplib.SMTPAuthenticationError(535, b"bad")

    monkeypatch.setattr(mail, "_send_smtp", boom)
    async with httpx.AsyncClient() as c:
        assert not await real_send(c, "a@b.com", "123456")
    get_settings.cache_clear()
