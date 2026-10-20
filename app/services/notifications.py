"""앱 내 알림 (PRD NOTI-01). FCM 대신 알림함 + 사용자 WebSocket 채널로 보낸다.

- 방해 금지: 22:00~08:00 KST에 생긴 알림은 다음 08:00부터 보인다(실시간 전송도 하지 않음).
- 사용자당 하루(KST) 5건 상한. 넘치면 저장하지 않는다.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import KST, aware, kst_day_start, utcnow
from app.db.session import defer_publish
from app.models import Notification
from app.realtime.broker import user_channel

DAILY_LIMIT = 5
QUIET_START = time(22)
QUIET_END = time(8)


def deliver_after(now: datetime) -> datetime:
    local = aware(now).astimezone(KST)
    t = local.time()
    if t >= QUIET_START:
        return datetime.combine(local.date() + timedelta(days=1), QUIET_END, KST).astimezone(now.tzinfo)
    if t < QUIET_END:
        return datetime.combine(local.date(), QUIET_END, KST).astimezone(now.tzinfo)
    return now


async def notify(
    session: AsyncSession,
    user_id: int,
    kind: str,
    body: str,
    link: str | None = None,
    now: datetime | None = None,
) -> Notification | None:
    """알림을 세션에 추가한다. 커밋은 호출한 쪽이 한다. 상한 초과면 None."""
    now = now or utcnow()
    sent_today = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.created_at >= kst_day_start(now))
    )
    if (sent_today or 0) >= DAILY_LIMIT:
        return None
    n = Notification(
        user_id=user_id,
        kind=kind,
        body=body[:280],
        link=link,
        deliver_after=deliver_after(now),
        created_at=now,
    )
    session.add(n)
    if n.deliver_after <= now:
        defer_publish(
            session,
            user_channel(user_id),
            "notification.created",
            {"kind": kind, "body": n.body, "link": link},
        )
    return n


async def already_notified(session: AsyncSession, user_id: int, kind: str, link: str) -> bool:
    return bool(
        await session.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id, Notification.kind == kind, Notification.link == link
            )
        )
    )


async def inbox(session: AsyncSession, user_id: int, now: datetime | None = None, limit: int = 30):
    now = now or utcnow()
    rows = await session.scalars(
        select(Notification)
        .where(Notification.user_id == user_id, Notification.deliver_after <= now)
        .order_by(Notification.id.desc())
        .limit(limit)
    )
    return list(rows)


async def unread_count(session: AsyncSession, user_id: int, now: datetime | None = None) -> int:
    now = now or utcnow()
    return (
        await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.deliver_after <= now,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


async def mark_all_read(session: AsyncSession, user_id: int, now: datetime | None = None) -> None:
    now = now or utcnow()
    await session.execute(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.deliver_after <= now,
        )
        .values(read_at=now)
        # 세션에 올라온 알림 객체를 파이썬에서 다시 평가하지 않는다. SQLite가 돌려준 시간대 없는 값과
        # 비교하다 TypeError가 난다. 화면은 이번 방문에 이 알림들을 '새 알림'으로 보여 주면 된다.
        .execution_options(synchronize_session=False)
    )
    await session.commit()
