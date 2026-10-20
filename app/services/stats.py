"""읽기 통계 · 배지 (docs/plans/2026-10-20-native-app-design.md '통계 · 배지').

- 분 = 인정된 체류시간(ReadingEvent.dwell_ms — 서버가 다시 계산해 깎은 값) 합 ÷ 60000, 내림.
- 날짜는 모두 KST. 이벤트 날짜는 occurred_at 기준(서버 시계 예산으로 이미 걸러진 값).
- 연속 기록은 '그날 검증된 청크가 하나라도 있는 날'(points.streak_days와 같은 규칙).
- 배지는 조회할 때 계산하고, 처음 달성한 순간을 badge 활동으로 남긴다(earned_at = 그 시각, 피드에도 뜬다).
  연속 배지처럼 나중에 조건이 깨져도 한 번 받은 배지는 그대로다.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import KST, aware, kst_date, kst_day_start, utcnow
from app.models import (
    Activity,
    Battle,
    BattleType,
    Follow,
    Highlight,
    LibraryEntry,
    PointsLog,
    Reaction,
    ReadingEvent,
    Shelf,
    User,
)
from app.services import activity, points

HEATMAP_DAYS = 84
WEEK_DAYS = 7
MS_PER_MINUTE = 60_000
NIGHT_START, NIGHT_END = time(22), time(4)


def minutes(ms: int) -> int:
    return int(ms) // MS_PER_MINUTE


@dataclass(slots=True)
class DayStat:
    date: date
    minutes: int
    chunks: int


@dataclass(slots=True)
class Stats:
    today_minutes: int
    week: list[DayStat]
    heatmap: list[DayStat]
    streak: int
    best_streak: int
    books_done: int
    books_done_year: int
    yearly_goal_books: int
    daily_goal_minutes: int
    total_minutes: int
    total_chunks: int
    reactions: int
    highlights: int


def best_run(days: set[date]) -> int:
    best = run = 0
    prev: date | None = None
    for d in sorted(days):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


async def _verified_times(session: AsyncSession, user_id: int) -> list[datetime]:
    return [
        aware(t)
        for t in await session.scalars(
            select(ReadingEvent.occurred_at).where(ReadingEvent.user_id == user_id, ReadingEvent.verified)
        )
    ]


async def _count(session: AsyncSession, stmt) -> int:
    return int(await session.scalar(stmt) or 0)


async def stats(session: AsyncSession, user: User, now: datetime | None = None) -> Stats:
    now = now or utcnow()
    today = kst_date(now)
    since = kst_day_start(now) - timedelta(days=HEATMAP_DAYS - 1)
    per_day_ms: dict[date, int] = defaultdict(int)
    per_day_chunks: dict[date, int] = defaultdict(int)
    rows = await session.execute(
        select(ReadingEvent.occurred_at, ReadingEvent.dwell_ms, ReadingEvent.verified).where(
            ReadingEvent.user_id == user.id, ReadingEvent.occurred_at >= since
        )
    )
    for at, ms, verified in rows.all():
        d = kst_date(at)
        per_day_ms[d] += ms or 0
        per_day_chunks[d] += 1 if verified else 0

    def days(n: int) -> list[DayStat]:
        return [
            DayStat(d, minutes(per_day_ms.get(d, 0)), per_day_chunks.get(d, 0))
            for d in (today - timedelta(days=i) for i in range(n - 1, -1, -1))
        ]

    verified_days = {kst_date(t) for t in await _verified_times(session, user.id)}
    total_ms, total_chunks = (
        await session.execute(
            select(
                func.coalesce(func.sum(ReadingEvent.dwell_ms), 0),
                func.count().filter(ReadingEvent.verified),
            ).where(ReadingEvent.user_id == user.id)
        )
    ).one()
    year_start = datetime.combine(date(today.year, 1, 1), time(), KST).astimezone(UTC)
    return Stats(
        today_minutes=minutes(per_day_ms.get(today, 0)),
        week=days(WEEK_DAYS),
        heatmap=days(HEATMAP_DAYS),
        streak=await points.streak_days(session, user.id, now),
        best_streak=best_run(verified_days),
        books_done=await _count(
            session,
            select(func.count())
            .select_from(LibraryEntry)
            .where(LibraryEntry.user_id == user.id, LibraryEntry.shelf == Shelf.DONE),
        ),
        # 올해 완독 = 올해 남은 finished 활동 중 지금도 완독 칸에 있는 책
        books_done_year=await _count(
            session,
            select(func.count(func.distinct(Activity.book_id)))
            .join(
                LibraryEntry,
                (LibraryEntry.user_id == Activity.user_id) & (LibraryEntry.book_id == Activity.book_id),
            )
            .where(
                Activity.user_id == user.id,
                Activity.kind == "finished",
                Activity.created_at >= year_start,
                LibraryEntry.shelf == Shelf.DONE,
            ),
        ),
        yearly_goal_books=user.yearly_goal_books,
        daily_goal_minutes=user.daily_goal_minutes,
        total_minutes=minutes(int(total_ms or 0)),
        total_chunks=int(total_chunks or 0),
        reactions=await _count(
            session, select(func.count()).select_from(Reaction).where(Reaction.user_id == user.id)
        ),
        highlights=await _count(
            session, select(func.count()).select_from(Highlight).where(Highlight.user_id == user.id)
        ),
    )


# ── 배지 ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BadgeDef:
    code: str
    title: str
    description: str
    icon: str
    metric: str
    goal: int


BADGES: tuple[BadgeDef, ...] = (
    BadgeDef("first_page", "첫 쪽", "앱에서 처음으로 한 청크를 끝까지 읽었어요.", "📖", "chunks", 1),
    BadgeDef("first_finish", "첫 완독", "책 한 권을 끝까지 읽었어요.", "🏁", "books_done", 1),
    BadgeDef("streak_3", "3일 연속", "3일 연속으로 읽었어요.", "🔥", "best_streak", 3),
    BadgeDef("streak_7", "7일 연속", "일주일 동안 하루도 빠짐없이 읽었어요.", "🔥", "best_streak", 7),
    BadgeDef("streak_30", "30일 연속", "한 달 내내 매일 읽었어요.", "🏆", "best_streak", 30),
    BadgeDef("reactions_10", "반응 10", "문단에 반응을 10번 남겼어요.", "💬", "reactions", 10),
    BadgeDef("highlights_10", "밑줄 10", "마음에 드는 문장에 밑줄을 10번 그었어요.", "🖍️", "highlights", 10),
    BadgeDef("friends_3", "친구 3", "친구를 3명 팔로우했어요.", "🤝", "following", 3),
    BadgeDef("race_win", "레이스 승리", "팀 페이지 레이스에서 이겼어요.", "🥇", "race_wins", 1),
    BadgeDef(
        "night_reader", "밤 독서", "밤 10시부터 새벽 4시 사이(KST)에 한 청크를 읽었어요.", "🌙", "night", 1
    ),
)


@dataclass(slots=True)
class BadgeView:
    code: str
    title: str
    description: str
    icon: str
    earned: bool
    earned_at: datetime | None
    progress: int
    goal: int


def _is_night(t: datetime) -> bool:
    local = aware(t).astimezone(KST).time()
    return local >= NIGHT_START or local < NIGHT_END


async def _race_wins(session: AsyncSession, user_id: int) -> int:
    """배틀 승리 포인트(ref_id = 'battle:{id}') 중 페이지 레이스였던 것."""
    refs = await session.scalars(
        select(PointsLog.ref_id).where(PointsLog.user_id == user_id, PointsLog.source == "battle_win")
    )
    ids = {int(r.split(":", 1)[1]) for r in refs if r and r.startswith("battle:") and r[7:].isdigit()}
    if not ids:
        return 0
    return await _count(
        session,
        select(func.count())
        .select_from(Battle)
        .where(Battle.id.in_(ids), Battle.type == BattleType.PAGE_RACE),
    )


async def _metrics(session: AsyncSession, user: User) -> dict[str, int]:
    verified = await _verified_times(session, user.id)
    return {
        "chunks": len(verified),
        "best_streak": best_run({kst_date(t) for t in verified}),
        "night": sum(1 for t in verified if _is_night(t)),
        "books_done": await _count(
            session,
            select(func.count())
            .select_from(LibraryEntry)
            .where(LibraryEntry.user_id == user.id, LibraryEntry.shelf == Shelf.DONE),
        ),
        "reactions": await _count(
            session, select(func.count()).select_from(Reaction).where(Reaction.user_id == user.id)
        ),
        "highlights": await _count(
            session, select(func.count()).select_from(Highlight).where(Highlight.user_id == user.id)
        ),
        "following": await _count(
            session, select(func.count()).select_from(Follow).where(Follow.follower_id == user.id)
        ),
        "race_wins": await _race_wins(session, user.id),
    }


async def badges(session: AsyncSession, user: User, now: datetime | None = None) -> list[BadgeView]:
    now = now or utcnow()
    metrics = await _metrics(session, user)
    earned_at: dict[str, datetime] = {
        ref.removeprefix("badge:"): aware(at)
        for ref, at in (
            await session.execute(
                select(Activity.ref, Activity.created_at).where(
                    Activity.user_id == user.id, Activity.kind == "badge"
                )
            )
        ).all()
        if ref
    }
    newly = False
    out = []
    for b in BADGES:
        value = metrics[b.metric]
        if b.code not in earned_at and value >= b.goal:
            await activity.badge_earned(session, user.id, b.code, b.title, now)
            earned_at[b.code] = now
            newly = True
        out.append(
            BadgeView(
                code=b.code,
                title=b.title,
                description=b.description,
                icon=b.icon,
                earned=b.code in earned_at,
                earned_at=earned_at.get(b.code),
                progress=min(value, b.goal),
                goal=b.goal,
            )
        )
    if newly:
        await session.commit()
    return out
