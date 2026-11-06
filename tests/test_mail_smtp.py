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


def test_smtp_falls_back_to_587(monkeypatch):
    import smtplib
    from types import SimpleNamespace

    calls = []

    class Dead:
        def __init__(self, host, port, **kw):
            calls.append(port)
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    class Ok:
        def __init__(self, host, port, **kw):
            calls.append(port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self, **kw):
            pass

        def login(self, u, p):
            assert p == "abcdefghijklmnop"

        def send_message(self, m):
            calls.append("sent")

    monkeypatch.setattr(smtplib, "SMTP_SSL", Dead)
    monkeypatch.setattr(smtplib, "SMTP", Ok)
    st = SimpleNamespace(smtp_host="smtp.gmail.com", smtp_port=465, smtp_user="me@gmail.com", smtp_password="abcd efgh ijkl mnop")
    mail._send_smtp(st, "a@b.com", "s", "t", "<p>h</p>")
    assert calls == [465, 587, "sent"]
