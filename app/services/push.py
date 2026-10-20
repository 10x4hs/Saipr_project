"""웹 푸시 (PRD NOTI-01의 FCM 대체). VAPID(RFC 8292)로 서버가 직접 서명하므로 외부 계정이 필요 없다.

- 키: 설정(VAPID_PRIVATE_KEY)이 없으면 처음 실행 때 파일로 만들어 둔다. 공개 키는 브라우저가 구독할 때 쓴다.
- 보내기: 알림이 '지금 보이는' 경우에만(방해 금지 시간이 아닐 때) 커밋 직후 백그라운드로 보낸다.
  pywebpush는 동기 HTTP라 스레드에서 돌린다. 404·410(구독 만료)이면 구독을 지운다.
"""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import PushSubscription

log = logging.getLogger(__name__)
TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str

    def info(self) -> dict:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


@lru_cache
def vapid() -> Vapid02:
    settings = get_settings()
    if settings.vapid_private_key:
        return Vapid02.from_string(settings.vapid_private_key)
    path = Path(settings.vapid_key_file)
    if path.exists():
        return Vapid02.from_file(str(path))
    key = Vapid02()
    key.generate_keys()
    key.save_key(str(path))
    log.info("generated VAPID key at %s", path)
    return key


def public_key() -> str:
    """브라우저 pushManager.subscribe의 applicationServerKey (base64url, 비압축 EC 점)."""
    raw = vapid().public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


async def subscribe(session: AsyncSession, user_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    sub = await session.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub is None:
        session.add(PushSubscription(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth))
    else:
        # 같은 브라우저로 다른 계정에 로그인하면 구독 주인을 바꾼다
        sub.user_id, sub.p256dh, sub.auth = user_id, p256dh, auth
    await session.commit()


async def unsubscribe(session: AsyncSession, user_id: int, endpoint: str) -> None:
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint
        )
    )
    await session.commit()


async def targets_of(session: AsyncSession, user_id: int) -> list[Target]:
    rows = await session.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
    return [Target(s.endpoint, s.p256dh, s.auth) for s in rows]


def _send_one(target: Target, payload: str) -> int | None:
    """보낸 결과 HTTP 상태. 예외 없이 끝나면 None."""
    try:
        resp = webpush(
            target.info(),
            payload,
            vapid_private_key=vapid(),
            vapid_claims={"sub": get_settings().vapid_subject},
            ttl=TTL_SECONDS,
            timeout=10,
        )
        log.info("web push sent: %s %s", getattr(resp, "status_code", "?"), target.endpoint[:40])
        return None
    except WebPushException as e:
        status = e.response.status_code if e.response is not None else None
        log.warning("web push failed (%s): %s", status, e)
        return status
    except Exception:  # 설정 오류·네트워크 오류도 백그라운드 작업을 죽이지 않고 기록만 한다
        log.exception("web push error")
        return None


async def send(targets: list[Target], data: dict) -> list[str]:
    """푸시를 보내고, 만료돼 지워야 할 endpoint 목록을 돌려준다."""
    payload = json.dumps(data, ensure_ascii=False)
    results = await asyncio.gather(*(asyncio.to_thread(_send_one, t, payload) for t in targets))
    expired = [t.endpoint for t, status in zip(targets, results, strict=True) if status in (404, 410)]
    if expired:
        async with SessionLocal() as s:
            await s.execute(delete(PushSubscription).where(PushSubscription.endpoint.in_(expired)))
            await s.commit()
    return expired
