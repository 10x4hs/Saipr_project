"""포인트 원장 · 챌린지 (PRD PNT-01).

- points_log는 append-only. 잔액은 SUM(amount). 행을 고치거나 지우지 않는다.
- 같은 사유로 두 번 적립되지 않도록 (user, source, ref_id)가 이미 있으면 건너뛴다.
- 챌린지는 '기간 키'(일=날짜, 주=ISO 주, 월=연-월)를 ref_id로 써서, 리셋 작업 없이 기간마다 1회만 지급된다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import KST, aware, kst_date, kst_day_start, kst_week_start, utcnow, week_key
from app.models import Book, Challenge, ChallengePeriod, LibraryEntry, PointsLog, ReadingEvent, Shelf
from app.services.notifications import notify

CHUNK_POINTS = 1
CHUNK_DAILY_CAP = 100
COMPLETE_POINTS = 50
BATTLE_WIN_POINTS = 100


@dataclass(frozen=True, slots=True)
class ChallengeDef:
    code: str
    title: str
    condition: dict
    reward_points: int
    period: ChallengePeriod


CHALLENGES: tuple[ChallengeDef, ...] = (
    ChallengeDef(
        "daily_5_chunks", "오늘 5청크 읽기", {"type": "daily_chunks", "count": 5}, 10, ChallengePeriod.DAILY
    ),
    ChallengeDef("streak_7", "7일 연속 읽기", {"type": "streak_days", "days": 7}, 70, ChallengePeriod.ONCE),
    ChallengeDef(
        "monthly_2_books",
        "이번 달 2권 완독",
        {"type": "monthly_done", "count": 2, "window": "month"},
        100,
        ChallengePeriod.ONCE,
    ),
    ChallengeDef(
        "weekly_30_chunks",
        "이번 주 30청크 읽기",
        {"type": "weekly_chunks", "count": 30},
        40,
        ChallengePeriod.WEEKLY,
    ),
)


async def ensure_challenges(session: AsyncSession) -> None:
    """코드에 정의된 챌린지를 DB에 맞춰 둔다(화면 표시용). 여러 번 불러도 안전."""
    existing = set(await session.scalars(select(Challenge.code)))
    for c in CHALLENGES:
        if c.code not in existing:
            session.add(
                Challenge(
                    code=c.code,
                    title=c.title,
                    condition=c.condition,
                    reward_points=c.reward_points,
                    period=c.period,
                )
            )
    await session.commit()


async def balance(session: AsyncSession, user_id: int) -> int:
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(PointsLog.amount), 0)).where(PointsLog.user_id == user_id)
        )
    )


async def history(session: AsyncSession, user_id: int, limit: int = 20) -> list[PointsLog]:
    return list(
        await session.scalars(
            select(PointsLog).where(PointsLog.user_id == user_id).order_by(PointsLog.id.desc()).limit(limit)
        )
    )


async def award(
    session: AsyncSession,
    user_id: int,
    source: str,
    amount: int,
    ref_id: str | None = None,
    now: datetime | None = None,
) -> bool:
    if amount <= 0:
        return False
    if ref_id is not None:
        dup = await session.scalar(
            select(PointsLog.id).where(
                PointsLog.user_id == user_id, PointsLog.source == source, PointsLog.ref_id == ref_id
            )
        )
        if dup:
            return False
    session.add(
        PointsLog(user_id=user_id, source=source, amount=amount, ref_id=ref_id, created_at=now or utcnow())
    )
    return True


async def award_chunks(session: AsyncSession, user_id: int, count: int, now: datetime) -> int:
    """청크 검증 1개 = 1P, KST 하루 100P 상한."""
    today = int(
        await session.scalar(
            select(func.coalesce(func.sum(PointsLog.amount), 0)).where(
                PointsLog.user_id == user_id,
                PointsLog.source == "chunk",
                PointsLog.created_at >= kst_day_start(now),
            )
        )
    )
    amount = min(count * CHUNK_POINTS, max(0, CHUNK_DAILY_CAP - today))
    if amount:
        session.add(PointsLog(user_id=user_id, source="chunk", amount=amount, created_at=now))
    return amount


# ── 챌린지 판정 ─────────────────────────────────────────────


def _period_ref(c: ChallengeDef, now: datetime) -> str:
    if c.condition.get("window") == "month":
        d = kst_date(now)
        return f"{c.code}:{d.year}-{d.month:02d}"
    if c.period is ChallengePeriod.DAILY:
        return f"{c.code}:{kst_date(now).isoformat()}"
    if c.period is ChallengePeriod.WEEKLY:
        return f"{c.code}:{week_key(now)}"
    return c.code


async def _verified_since(session: AsyncSession, user_id: int, since: datetime) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ReadingEvent)
            .where(ReadingEvent.user_id == user_id, ReadingEvent.verified, ReadingEvent.occurred_at >= since)
        )
    )


async def _streak_days(session: AsyncSession, user_id: int, now: datetime) -> int:
    since = kst_day_start(now) - timedelta(days=40)
    times = await session.scalars(
        select(ReadingEvent.occurred_at).where(
            ReadingEvent.user_id == user_id, ReadingEvent.verified, ReadingEvent.occurred_at >= since
        )
    )
    days = {aware(t).astimezone(KST).date() for t in times}
    d, streak = kst_date(now), 0
    while d in days:
        streak += 1
        d -= timedelta(days=1)
    return streak


async def streak_days(session: AsyncSession, user_id: int, now: datetime | None = None) -> int:
    """오늘(KST)까지 며칠 연속으로 한 청크 이상 읽었는가. 오늘 아직 안 읽었으면 어제까지로 센다."""
    now = now or utcnow()
    today = await _streak_days(session, user_id, now)
    return today or await _streak_days(session, user_id, now - timedelta(days=1))


async def _done_this_month(session: AsyncSession, user_id: int, now: datetime) -> int:
    d = kst_date(now)
    month_start = kst_day_start(now) - timedelta(days=d.day - 1)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(PointsLog)
            .where(
                PointsLog.user_id == user_id,
                PointsLog.source == "complete",
                PointsLog.created_at >= month_start,
            )
        )
    )


async def progress_of(session: AsyncSession, user_id: int, c: ChallengeDef, now: datetime) -> int:
    kind = c.condition["type"]
    if kind == "daily_chunks":
        return await _verified_since(session, user_id, kst_day_start(now))
    if kind == "weekly_chunks":
        return await _verified_since(session, user_id, kst_week_start(now))
    if kind == "streak_days":
        return await _streak_days(session, user_id, now)
    if kind == "monthly_done":
        return await _done_this_month(session, user_id, now)
    return 0


def goal_of(c: ChallengeDef) -> int:
    return int(c.condition.get("count") or c.condition.get("days") or 1)


async def evaluate_challenges(
    session: AsyncSession, user_id: int, now: datetime | None = None
) -> list[ChallengeDef]:
    """달성한 챌린지를 지급하고 목록을 돌려준다. 세션은 flush된 상태여야 방금 기록한 이벤트가 보인다."""
    now = now or utcnow()
    done: list[ChallengeDef] = []
    for c in CHALLENGES:
        if await progress_of(session, user_id, c, now) >= goal_of(c):
            if await award(session, user_id, "challenge", c.reward_points, _period_ref(c, now), now):
                done.append(c)
                await notify(
                    session, user_id, "challenge", f"챌린지 달성: {c.title} (+{c.reward_points}P)", "/me", now
                )
    return done


def finished_reading(entry: LibraryEntry, book: Book) -> bool:
    """앱 안에서 마지막 청크까지 검증됐는가."""
    return book.has_fulltext and book.total_chunks > 0 and entry.verified_chunk + 1 >= book.total_chunks


async def complete_book(
    session: AsyncSession, entry: LibraryEntry, book: Book, now: datetime | None = None
) -> bool:
    """완독 칸으로 옮긴다. 완독 포인트(+50P, 책당 1회)는 앱 안에서 끝까지 검증된 책에만 준다.

    트래커 도서의 진행률은 본인이 입력한 값이라 확인할 수 없다. 여기에도 포인트를 주면
    가짜 책을 계속 등록해 포인트를 무한히 받을 수 있으므로 서재 상태만 바꾼다
    (레이스에서 트래커를 빼는 것과 같은 원칙, PRD READ-02).
    """
    now = now or utcnow()
    entry.shelf = Shelf.DONE
    if not book.has_fulltext:
        entry.progress_pct = 100
    if not finished_reading(entry, book):
        return False
    awarded = await award(session, entry.user_id, "complete", COMPLETE_POINTS, f"book:{entry.book_id}", now)
    await session.flush()
    await evaluate_challenges(session, entry.user_id, now)
    return awarded
