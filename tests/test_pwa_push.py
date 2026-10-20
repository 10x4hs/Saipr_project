"""PWA(서비스 워커·매니페스트·오프라인) · VAPID 웹 푸시 · 연속 읽기."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.clock import KST
from app.models import PushSubscription, ReadingEvent, User
from app.services import notifications as noti
from app.services import points, push
from tests.conftest import signup

SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {
        "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
        "auth": "tBHItJI5svbpez7KI4CCXg",
    },
}


async def test_service_worker_manifest_offline(api):
    async with api() as c:
        sw = await c.get("/sw.js")
        assert sw.status_code == 200 and sw.headers["service-worker-allowed"] == "/"
        assert sw.headers["cache-control"] == "no-cache" and "saipr-v" in sw.text
        m = (await c.get("/manifest.webmanifest")).json()
        assert m["display"] == "standalone" and m["lang"] == "ko"
        for icon in m["icons"]:
            assert (await c.get(icon["src"])).status_code == 200
        off = await c.get("/offline", headers={"accept": "text/html"})
        assert off.status_code == 200 and "오프라인" in off.text


async def test_pages_link_pwa_and_motion(api):
    async with api() as c:
        await signup(c)
        html = (await c.get("/", headers={"accept": "text/html"})).text
    for needle in (
        'rel="manifest"',
        "speculationrules",
        "motion.css",
        "pwa.js",
        "liquid-refract",
        "tab-pill",
    ):
        assert needle in html, needle


async def test_vapid_public_key_is_uncompressed_p256_point(api):
    async with api() as c:
        key = (await c.get("/api/v1/push/key")).json()["public_key"]
    raw = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
    assert len(raw) == 65 and raw[0] == 0x04


async def test_subscribe_requires_login_and_https(api, session_factory):
    async with api() as c:
        assert (await c.post("/api/v1/push/subscribe", json=SUB)).status_code in (401, 403)
        await signup(c)
        bad = {**SUB, "endpoint": "http://evil.example/push"}
        assert (await c.post("/api/v1/push/subscribe", json=bad)).status_code == 422
        assert (await c.post("/api/v1/push/subscribe", json=SUB)).status_code == 204
        assert (await c.post("/api/v1/push/subscribe", json=SUB)).status_code == 204  # 다시 해도 하나
        async with session_factory() as s:
            assert await s.scalar(select(func.count()).select_from(PushSubscription)) == 1
        assert (
            await c.post("/api/v1/push/unsubscribe", json={"endpoint": SUB["endpoint"]})
        ).status_code == 204
        async with session_factory() as s:
            assert await s.scalar(select(func.count()).select_from(PushSubscription)) == 0


async def _user_with_sub(session_factory) -> int:
    async with session_factory() as s:
        u = User(nickname="푸시")
        s.add(u)
        await s.flush()
        s.add(
            PushSubscription(
                user_id=u.id, endpoint=SUB["endpoint"], p256dh=SUB["keys"]["p256dh"], auth=SUB["keys"]["auth"]
            )
        )
        await s.commit()
        return u.id


async def test_notification_sends_web_push_after_commit(session_factory, monkeypatch):
    sent = []
    monkeypatch.setattr(
        push, "_send_one", lambda target, payload: sent.append((target.endpoint, json.loads(payload)))
    )
    uid = await _user_with_sub(session_factory)
    noon = datetime(2026, 10, 20, 12, tzinfo=KST).astimezone(UTC)
    async with session_factory() as s:
        await noti.notify(s, uid, "reaction", "준호님이 반응을 남겼어요", "/books/1/read", now=noon)
        assert sent == []  # 커밋 전에는 보내지 않는다
        await s.commit()
    await asyncio.sleep(0.05)
    assert len(sent) == 1
    endpoint, data = sent[0]
    assert endpoint == SUB["endpoint"]
    assert (
        data["body"] == "준호님이 반응을 남겼어요" and data["url"] == "/books/1/read" and data["badge"] == 1
    )


async def test_no_push_in_quiet_hours_or_on_rollback(session_factory, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "_send_one", lambda target, payload: sent.append(payload))
    uid = await _user_with_sub(session_factory)
    night = datetime(2026, 10, 20, 23, tzinfo=KST).astimezone(UTC)
    noon = datetime(2026, 10, 20, 12, tzinfo=KST).astimezone(UTC)
    async with session_factory() as s:
        await noti.notify(s, uid, "t", "밤 알림", now=night)
        await s.commit()
        await noti.notify(s, uid, "t", "취소될 알림", now=noon)
        await s.rollback()
    await asyncio.sleep(0.05)
    assert sent == []


async def test_expired_subscription_is_removed(session_factory, monkeypatch):
    monkeypatch.setattr(push, "_send_one", lambda target, payload: 410)
    monkeypatch.setattr(push, "SessionLocal", session_factory)
    uid = await _user_with_sub(session_factory)
    async with session_factory() as s:
        targets = await push.targets_of(s, uid)
    assert await push.send(targets, {"body": "x"}) == [SUB["endpoint"]]
    async with session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(PushSubscription)) == 0


async def test_test_push_endpoint_actually_sends(api, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "_send_one", lambda target, payload: sent.append(json.loads(payload)))
    async with api() as c:
        await signup(c)
        await c.post("/api/v1/push/subscribe", json=SUB)
        r = await c.post("/api/v1/push/test")
        await asyncio.sleep(0.1)
    assert r.status_code == 202 and r.json()["subscriptions"] == 1
    assert [d["kind"] for d in sent] == ["test"]


async def test_streak_counts_consecutive_days(session_factory):
    now = datetime(2026, 10, 20, 12, tzinfo=KST).astimezone(UTC)
    async with session_factory() as s:
        u = User(nickname="연속")
        s.add(u)
        await s.flush()
        for back in (1, 2, 3, 5):  # 어제·그제·사흘 전 연속, 닷새 전은 끊김
            s.add(
                ReadingEvent(
                    user_id=u.id,
                    book_id=1,
                    chunk_index=back,
                    dwell_ms=1,
                    verified=True,
                    occurred_at=now - timedelta(days=back),
                )
            )
        await s.commit()
        assert await points.streak_days(s, u.id, now) == 3  # 오늘 아직 안 읽었으면 어제까지


def test_vapid_signature_is_valid_with_default_settings(tmp_path, monkeypatch):
    """실제 서명까지 만들어 본다 (네트워크 없이 curl 문자열로) — 설정값이 라이브러리 규칙에 맞는지 확인.
    curl 모드는 암호화된 본문을 현재 폴더에 encrypted.data로 쓰므로 임시 폴더에서 돌린다."""
    monkeypatch.chdir(tmp_path)
    from pywebpush import webpush

    from app.core.config import get_settings

    curl = webpush(
        SUB,
        "hi",
        vapid_private_key=push.vapid(),
        vapid_claims={"sub": get_settings().vapid_subject},
        curl=True,
    )
    assert "vapid t=" in curl and SUB["endpoint"] in curl
