"""네이티브 앱용 Bearer 토큰 (docs/plans/2026-10-20-native-app-design.md '인증').

- 원문 토큰은 발급 응답에서 한 번만 보여 주고, DB에는 SHA-256 해시만 둔다(유출돼도 원문을 알 수 없다).
- 만료는 발급 뒤 90일 고정. 만료된 토큰은 조회할 때 지운다.
- 마지막 사용 시각은 매 요청마다 쓰지 않고 1시간에 한 번만 갱신한다.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import aware, utcnow
from app.models import ApiToken, User
from app.realtime.broker import broker, user_channel

TOKEN_TTL = timedelta(days=90)
TOUCH_INTERVAL = timedelta(hours=1)
# 원문 토큰 길이 상한. 터무니없이 긴 헤더로 해시 계산을 시키지 않는다
MAX_TOKEN_LEN = 200
REVOKED = "session.revoked"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue(session: AsyncSession, user: User, now: datetime | None = None) -> str:
    """새 토큰을 만들고 커밋한다. 원문을 돌려준다."""
    now = now or utcnow()
    raw = secrets.token_urlsafe(32)
    # 지난 토큰 중 만료된 것은 이 기회에 정리한다
    await session.execute(delete(ApiToken).where(ApiToken.user_id == user.id, ApiToken.expires_at <= now))
    session.add(
        ApiToken(
            token_hash=hash_token(raw),
            user_id=user.id,
            created_at=now,
            expires_at=now + TOKEN_TTL,
        )
    )
    await session.commit()
    return raw


async def lookup(
    session: AsyncSession, raw: str, now: datetime | None = None
) -> tuple[ApiToken, User] | None:
    """유효한 토큰이면 (토큰, 사용자). 없거나 만료면 None."""
    if not raw or len(raw) > MAX_TOKEN_LEN:
        return None
    now = now or utcnow()
    row = (
        await session.execute(
            select(ApiToken, User)
            .join(User, User.id == ApiToken.user_id)
            .where(ApiToken.token_hash == hash_token(raw))
        )
    ).first()
    if row is None:
        return None
    token, user = row
    if aware(token.expires_at) <= now:
        await session.delete(token)
        await session.commit()
        return None
    if token.last_used_at is None or now - aware(token.last_used_at) >= TOUCH_INTERVAL:
        await session.execute(
            update(ApiToken)
            .where(ApiToken.id == token.id)
            .values(last_used_at=now)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    return token, user


async def revoke(session: AsyncSession, token: ApiToken) -> None:
    await session.execute(delete(ApiToken).where(ApiToken.id == token.id))
    await session.commit()
    # 이 토큰으로 열려 있던 WebSocket도 닫는다 (ws.py가 이 이벤트를 보고 1008로 끊는다)
    broker.publish(user_channel(token.user_id), REVOKED, {"token_id": token.id})
