"""친구 피드에 남는 활동 (docs/plans/2026-10-20-native-app-design.md '친구 · 피드').

kind: started · milestone(data.pct) · finished · highlight(data.quote, data.note)
· joined_room(data.room_name) · badge(data.title)

- 서비스 코드(읽기 · 진행률 · 완독 · 밑줄 · 방 입장 · 배지)가 같은 트랜잭션 안에서 부른다.
  커밋은 부른 쪽이 한다.
- ref가 있는 활동은 사람마다 한 번만 남는다. 동시에 두 요청이 같은 활동을 남기려 해도 커밋이 실패하지 않도록
  INSERT ... ON CONFLICT DO NOTHING을 쓴다(SQLite · Postgres 모두 지원).
- 피드는 내가 팔로우한 사람 + 나. 밑줄 문장은 보는 사람의 스포일러 가드를 거친다.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models import Activity, Book, Follow, LibraryEntry, User
from app.services import library

MILESTONES = (25, 50, 75)
FEED_MAX = 50


def _insert(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    return (postgresql.insert if dialect == "postgresql" else sqlite.insert)(Activity)


async def record(
    session: AsyncSession,
    user_id: int,
    kind: str,
    book_id: int | None = None,
    data: dict[str, Any] | None = None,
    ref: str | None = None,
    now: datetime | None = None,
) -> None:
    values = {
        "user_id": user_id,
        "kind": kind,
        "book_id": book_id,
        "data": data or {},
        "ref": ref,
        "created_at": now or utcnow(),
    }
    stmt = _insert(session).values(**values)
    if ref is not None:
        stmt = stmt.on_conflict_do_nothing()
    await session.execute(stmt)


async def progress_changed(
    session: AsyncSession, user_id: int, book_id: int, before_pct: int, after_pct: int, now: datetime
) -> None:
    """진행률이 올랐을 때: 처음 시작 · 25/50/75% 돌파 · 100% 완독."""
    if after_pct <= before_pct:
        return
    if before_pct == 0:
        await record(session, user_id, "started", book_id, ref=f"started:{book_id}", now=now)
    for pct in MILESTONES:
        if before_pct < pct <= after_pct < 100:
            await record(
                session,
                user_id,
                "milestone",
                book_id,
                {"pct": pct},
                ref=f"milestone:{book_id}:{pct}",
                now=now,
            )
    if after_pct >= 100:
        await finished(session, user_id, book_id, now)


async def finished(session: AsyncSession, user_id: int, book_id: int, now: datetime | None = None) -> None:
    await record(session, user_id, "finished", book_id, ref=f"finished:{book_id}", now=now)


def highlight_ref(highlight_id: int) -> str:
    return f"highlight:{highlight_id}"


def highlight_data(quote: str, note: str | None, chunk_index: int, highlight_id: int) -> dict[str, Any]:
    return {"quote": quote, "note": note, "chunk_index": chunk_index, "highlight_id": highlight_id}


async def highlight_shared(
    session: AsyncSession,
    user_id: int,
    book_id: int,
    highlight_id: int,
    quote: str,
    note: str | None,
    chunk_index: int,
    now: datetime | None = None,
) -> None:
    """친구 공개 밑줄을 피드에 올리거나(처음) 메모를 고친 내용으로 맞춘다."""
    ref = highlight_ref(highlight_id)
    data = highlight_data(quote, note, chunk_index, highlight_id)
    result = await session.execute(
        update(Activity)
        .where(Activity.user_id == user_id, Activity.ref == ref)
        .values(data=data)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        await record(session, user_id, "highlight", book_id, data, ref=ref, now=now)


async def highlight_hidden(session: AsyncSession, user_id: int, highlight_id: int) -> None:
    """나만 보기로 바꾸거나 지운 밑줄은 피드에서도 지운다."""
    await session.execute(
        delete(Activity)
        .where(Activity.user_id == user_id, Activity.ref == highlight_ref(highlight_id))
        .execution_options(synchronize_session=False)
    )


async def joined_room(
    session: AsyncSession,
    user_id: int,
    book_id: int,
    room_id: int,
    room_name: str,
    now: datetime | None = None,
) -> None:
    await record(
        session, user_id, "joined_room", book_id, {"room_name": room_name}, ref=f"room:{room_id}", now=now
    )


async def badge_earned(
    session: AsyncSession, user_id: int, code: str, title: str, now: datetime | None = None
) -> None:
    await record(
        session, user_id, "badge", None, {"code": code, "title": title}, ref=f"badge:{code}", now=now
    )


# ── 피드 ─────────────────────────────────────────────────


@dataclass(slots=True)
class FeedItem:
    activity: Activity
    user: User
    book: Book | None
    data: dict[str, Any]


def following_ids_query(user_id: int):
    return select(Follow.followee_id).where(Follow.follower_id == user_id)


async def feed(
    session: AsyncSession, viewer: User, before: int | None = None, limit: int = 20
) -> list[FeedItem]:
    limit = max(1, min(FEED_MAX, limit))
    q = (
        select(Activity, User)
        .join(User, User.id == Activity.user_id)
        .where(or_(Activity.user_id == viewer.id, Activity.user_id.in_(following_ids_query(viewer.id))))
        .order_by(Activity.id.desc())
        .limit(limit)
    )
    if before is not None:
        q = q.where(Activity.id < before)
    rows = (await session.execute(q)).all()

    book_ids = {a.book_id for a, _ in rows if a.book_id is not None}
    books = (
        {b.id: b for b in await session.scalars(select(Book).where(Book.id.in_(book_ids)))}
        if book_ids
        else {}
    )
    positions = await viewer_positions(session, viewer, books.values())
    out = []
    for a, u in rows:
        book = books.get(a.book_id) if a.book_id is not None else None
        data = dict(a.data or {})
        if a.kind == "highlight":
            data = guard_quote(data, viewer, u.id, positions.get(a.book_id, -1))
        out.append(FeedItem(a, u, book, data))
    return out


async def viewer_positions(session: AsyncSession, viewer: User, books) -> dict[int, int]:
    """보는 사람의 책별 위치(스포일러 가드 기준)를 한 번에."""
    books = {b.id: b for b in books}
    if not books:
        return {}
    entries = await session.scalars(
        select(LibraryEntry).where(LibraryEntry.user_id == viewer.id, LibraryEntry.book_id.in_(books))
    )
    by_book = {e.book_id: e for e in entries}
    return {bid: library.position_of(by_book.get(bid), b) for bid, b in books.items()}


def guard_quote(data: dict[str, Any], viewer: User, author_id: int, position: int) -> dict[str, Any]:
    """내 위치보다 뒤의 밑줄은 문장·메모를 가리고 locked=True만 남긴다(스포일러 가드를 켠 사람만)."""
    chunk = data.get("chunk_index")
    if viewer.id == author_id or not viewer.spoiler_guard or not isinstance(chunk, int) or chunk <= position:
        return {**data, "locked": False}
    return {
        **{k: v for k, v in data.items() if k not in ("quote", "note")},
        "quote": None,
        "note": None,
        "locked": True,
    }
