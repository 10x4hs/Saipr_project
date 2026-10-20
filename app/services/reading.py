"""리더 이벤트 수집 · 체류시간 판정 (PRD READ-01, BTL-01, 5장 '치팅 방지 서버 신뢰').

클라이언트는 청크가 화면에 머문 시간(dwell_ms)과 보기를 끝낸 시각(occurred_at)을 10초마다 묶어 보낸다.
서버는 그 값을 그대로 믿지 않는다.

1. 인정 체류시간 = min(보낸 값, 직전 이벤트와의 시각 간격, 최소 체류시간 × 10)
   → 시각 간격보다 길게 읽었다고 주장할 수 없고, 탭을 켜두고 방치해도 상한에 걸린다.
2. occurred_at은 클라이언트가 정하는 값이라 그것만으로는 믿을 수 없다. 그래서 **서버 시계**로 한 번 더 막는다.
   - 마지막으로 받은 배치의 서버 수신 시각(received_at)보다 앞선 시각의 이벤트는 인정 0
   - 한 배치의 인정 시간 합 ≤ 직전 배치 수신 뒤(처음이면 가입 뒤) 실제로 흐른 시간
   → "쉬다가 지난 하루 동안 읽었다고 한꺼번에 보내기"로 실제 흐른 시간보다 많이 읽은 척할 수 없다.
3. 같은 청크의 인정 체류시간을 누적해 최소 체류시간을 넘는 순간 그 이벤트를 verified=True로 기록한다.
   한 청크는 한 번만 verified가 되고(DB 조건부 UNIQUE), 레이스 점수 = verified 이벤트 수.
4. 레이스 점수는 '실시간으로 도착한' 이벤트만 인정한다(발생 후 10분 안에 수신).
   PRD EXC-05는 24시간이었지만, 그 창이 길수록 오프라인이라고 둘러대며 시각을 꾸며 낼 여지가 커서 줄였다.
   늦은 이벤트도 진행률에는 반영한다.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import aware, utcnow
from app.models import Book, BookChunk, ReadingEvent, Shelf, User
from app.services import activity, library, points, rooms
from app.services.pace import credited_dwell_ms, is_verified, min_dwell_ms

MAX_BATCH = 200
FUTURE_SKEW = timedelta(seconds=30)
RACE_LATE_LIMIT = timedelta(minutes=10)
BUDGET_SLACK = timedelta(seconds=30)
SYNC_WINDOW = timedelta(minutes=2)
SLOW_DOWN_WINDOW = timedelta(minutes=1)
SLOW_DOWN_STREAK = 5


class ReadingError(Exception):
    pass


@dataclass(slots=True)
class EventIn:
    chunk_index: int
    dwell_ms: int
    occurred_at: datetime


@dataclass(slots=True)
class BatchResult:
    accepted: int = 0
    newly_verified: list[int] = field(default_factory=list)
    verified_chunk: int = -1
    progress_pct: int = 0
    points_awarded: int = 0
    # 1분 안에 미검증 청크가 5개 이상 이어지면 "천천히 읽어도 괜찮아요" 안내 (징벌 아님)
    slow_down: bool = False


async def _verified_chunks(session: AsyncSession, user_id: int, book_id: int) -> set[int]:
    rows = await session.scalars(
        select(ReadingEvent.chunk_index).where(
            ReadingEvent.user_id == user_id, ReadingEvent.book_id == book_id, ReadingEvent.verified
        )
    )
    return set(rows)


async def _dwell_totals(session: AsyncSession, user_id: int, book_id: int, idx: set[int]) -> dict[int, int]:
    rows = await session.execute(
        select(ReadingEvent.chunk_index, func.sum(ReadingEvent.dwell_ms))
        .where(
            ReadingEvent.user_id == user_id,
            ReadingEvent.book_id == book_id,
            ReadingEvent.chunk_index.in_(idx),
        )
        .group_by(ReadingEvent.chunk_index)
    )
    return {i: int(total or 0) for i, total in rows.all()}


async def record_events(
    session: AsyncSession, user: User, book: Book, events: list[EventIn], now: datetime | None = None
) -> BatchResult:
    now = now or utcnow()
    if not book.has_fulltext:
        raise ReadingError("트래커 모드 도서는 리더 이벤트를 받지 않아요.")
    if len(events) > MAX_BATCH:
        raise ReadingError(f"한 번에 최대 {MAX_BATCH}개까지 보낼 수 있어요.")

    valid = sorted(
        (
            e
            for e in events
            if 0 <= e.chunk_index < book.total_chunks
            and e.dwell_ms >= 0
            and aware(e.occurred_at) <= now + FUTURE_SKEW
        ),
        key=lambda e: aware(e.occurred_at),
    )
    result = BatchResult()
    entry = await library.ensure_entry(session, user.id, book.id)
    if not valid:
        result.verified_chunk, result.progress_pct = entry.verified_chunk, entry.progress_pct
        return result

    indices = {e.chunk_index for e in valid}
    texts = dict(
        (
            await session.execute(
                select(BookChunk.chunk_index, BookChunk.text).where(
                    BookChunk.book_id == book.id, BookChunk.chunk_index.in_(indices)
                )
            )
        ).all()
    )
    min_ms = {i: min_dwell_ms(t, book.language) for i, t in texts.items()}
    totals = await _dwell_totals(session, user.id, book.id, indices)
    already = await _verified_chunks(session, user.id, book.id)
    prev_at = await session.scalar(
        select(func.max(ReadingEvent.occurred_at)).where(ReadingEvent.user_id == user.id)
    )
    # 기준선은 '지난 동기화'. 방금(SYNC_WINDOW 안에) 받은 배치는 같은 동기화의 앞부분으로 본다 —
    # 오프라인으로 오래 읽은 기록을 여러 배치·여러 책으로 나눠 보내도 뒤 배치가 0이 되지 않게.
    # 겹쳐 받는 것은 막힌다: 각 이벤트는 직전 이벤트 시각(prev) 뒤의 간격만큼만 인정된다.
    last_received = await session.scalar(
        select(func.max(ReadingEvent.received_at)).where(
            ReadingEvent.user_id == user.id, ReadingEvent.received_at < now - SYNC_WINDOW
        )
    )
    prev = aware(prev_at) if prev_at else None
    floor = aware(last_received) if last_received else aware(user.created_at or now)
    budget_ms = int((now - floor + BUDGET_SLACK).total_seconds() * 1000)

    for e in valid:
        at = aware(e.occurred_at)
        claimed = e.dwell_ms
        if at < floor:
            claimed = 0  # 지난 동기화보다 앞선 시각 — 이미 보냈어야 할 이벤트
        if prev is not None:
            gap_ms = int((at - prev).total_seconds() * 1000)
            claimed = min(claimed, max(0, gap_ms))
        credited = min(credited_dwell_ms(claimed, min_ms[e.chunk_index]), max(0, budget_ms))
        budget_ms -= credited
        totals[e.chunk_index] = totals.get(e.chunk_index, 0) + credited
        verified = e.chunk_index not in already and is_verified(totals[e.chunk_index], min_ms[e.chunk_index])
        if verified:
            already.add(e.chunk_index)
            result.newly_verified.append(e.chunk_index)
        session.add(
            ReadingEvent(
                user_id=user.id,
                book_id=book.id,
                chunk_index=e.chunk_index,
                dwell_ms=credited,
                verified=verified,
                race_eligible=now - at <= RACE_LATE_LIMIT,
                occurred_at=at,
                received_at=now,
            )
        )
        prev = max(prev, at) if prev else at
        result.accepted += 1

    before, before_pct = entry.verified_chunk, entry.progress_pct
    if result.newly_verified:
        entry.verified_chunk = max(entry.verified_chunk, *result.newly_verified)
        entry.progress_pct = min(100, (entry.verified_chunk + 1) * 100 // book.total_chunks)
        if entry.shelf is Shelf.WANT:
            entry.shelf = Shelf.READING
        result.points_awarded = await points.award_chunks(session, user.id, len(result.newly_verified), now)
        # 친구 피드: 첫 청크 · 25/50/75% · 끝까지
        if before < 0:
            await activity.record(session, user.id, "started", book.id, ref=f"started:{book.id}", now=now)
        await activity.progress_changed(session, user.id, book.id, before_pct, entry.progress_pct, now)

    await session.flush()
    result.slow_down = await _needs_slow_down(session, user.id, book.id, now)
    if result.newly_verified:
        await points.evaluate_challenges(session, user.id, now)
        await rooms.broadcast_progress(session, user, book, entry, before, len(result.newly_verified))
    await session.commit()

    result.verified_chunk, result.progress_pct = entry.verified_chunk, entry.progress_pct
    return result


async def _needs_slow_down(session: AsyncSession, user_id: int, book_id: int, now: datetime) -> bool:
    recent = list(
        await session.execute(
            select(ReadingEvent.chunk_index, ReadingEvent.verified)
            .where(
                ReadingEvent.user_id == user_id,
                ReadingEvent.book_id == book_id,
                ReadingEvent.occurred_at >= now - SLOW_DOWN_WINDOW,
            )
            .order_by(ReadingEvent.occurred_at.desc(), ReadingEvent.id.desc())
        )
    )
    verified = await _verified_chunks(session, user_id, book_id)
    streak, seen = 0, set()
    for idx, _ in recent:
        if idx in verified:
            break
        if idx not in seen:
            seen.add(idx)
            streak += 1
    return streak >= SLOW_DOWN_STREAK
