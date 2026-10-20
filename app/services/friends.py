"""친구 찾기 · 팔로우 · 응원 · 프로필 (docs/plans/2026-10-20-native-app-design.md '친구 · 피드')."""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import kst_date, kst_week_start, utcnow
from app.models import (
    FRIEND_CODE_ALPHABET,
    FRIEND_CODE_LEN,
    Book,
    Cheer,
    Follow,
    Highlight,
    LibraryEntry,
    ReadingEvent,
    Shelf,
    User,
)
from app.services import points
from app.services.notifications import notify

SEARCH_LIMIT = 20
PROFILE_HIGHLIGHTS = 5
LIST_LIMIT = 200


class FriendError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


async def get_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise FriendError("사용자를 찾을 수 없어요.", 404)
    return user


def _looks_like_code(q: str) -> bool:
    return len(q) == FRIEND_CODE_LEN and all(ch in FRIEND_CODE_ALPHABET for ch in q.upper())


async def search(session: AsyncSession, viewer: User, q: str) -> list[User]:
    """닉네임 부분 일치 또는 친구 코드 정확히 일치. 나 자신은 빼고, 코드가 맞은 사람을 맨 앞에."""
    q = q.strip()
    if not 1 <= len(q) <= 40:
        raise FriendError("검색어는 1~40자로 써 주세요.")
    by_code: list[User] = []
    if _looks_like_code(q):
        found = await session.scalar(select(User).where(User.friend_code == q.upper(), User.id != viewer.id))
        if found:
            by_code.append(found)
    rows = await session.scalars(
        select(User)
        .where(User.nickname.contains(q, autoescape=True), User.id != viewer.id)
        .order_by(func.length(User.nickname), User.id)
        .limit(SEARCH_LIMIT)
    )
    seen = {u.id for u in by_code}
    return (by_code + [u for u in rows if u.id not in seen])[:SEARCH_LIMIT]


async def following_set(session: AsyncSession, follower_id: int, ids) -> set[int]:
    ids = set(ids)
    if not ids:
        return set()
    return set(
        await session.scalars(
            select(Follow.followee_id).where(Follow.follower_id == follower_id, Follow.followee_id.in_(ids))
        )
    )


async def is_following(session: AsyncSession, follower_id: int, followee_id: int) -> bool:
    return bool(await following_set(session, follower_id, [followee_id]))


async def follow(session: AsyncSession, me: User, target_id: int, now: datetime | None = None) -> None:
    """이미 팔로우 중이면 아무 일도 하지 않는다(여러 번 눌러도 같은 결과)."""
    if target_id == me.id:
        raise FriendError("나 자신은 팔로우할 수 없어요.")
    target = await get_user(session, target_id)
    if await session.get(Follow, (me.id, target.id)):
        return
    now = now or utcnow()
    session.add(Follow(follower_id=me.id, followee_id=target.id, created_at=now))
    await notify(session, target.id, "follow", f"{me.nickname}님이 나를 팔로우했어요.", None, now)
    try:
        await session.commit()
    except IntegrityError:
        # 같은 사람이 동시에 두 번 눌렀다 — 이미 팔로우된 상태다
        await session.rollback()


async def unfollow(session: AsyncSession, me: User, target_id: int) -> None:
    if target_id == me.id:
        raise FriendError("나 자신은 팔로우할 수 없어요.")
    await get_user(session, target_id)
    await session.execute(delete(Follow).where(Follow.follower_id == me.id, Follow.followee_id == target_id))
    await session.commit()


async def following(session: AsyncSession, user_id: int) -> list[User]:
    return list(
        await session.scalars(
            select(User)
            .join(Follow, Follow.followee_id == User.id)
            .where(Follow.follower_id == user_id)
            .order_by(Follow.created_at.desc(), User.id)
            .limit(LIST_LIMIT)
        )
    )


async def followers(session: AsyncSession, user_id: int) -> list[User]:
    return list(
        await session.scalars(
            select(User)
            .join(Follow, Follow.follower_id == User.id)
            .where(Follow.followee_id == user_id)
            .order_by(Follow.created_at.desc(), User.id)
            .limit(LIST_LIMIT)
        )
    )


async def follow_counts(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """(팔로워 수, 팔로잉 수)."""
    n_followers = await session.scalar(
        select(func.count()).select_from(Follow).where(Follow.followee_id == user_id)
    )
    n_following = await session.scalar(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )
    return int(n_followers or 0), int(n_following or 0)


async def cheer(session: AsyncSession, me: User, target_id: int, now: datetime | None = None) -> bool:
    """응원 알림. 같은 사람에게는 KST 하루 한 번. 알림 상한(하루 5건)에 걸리면 False."""
    if target_id == me.id:
        raise FriendError("나 자신은 응원할 수 없어요.")
    target = await get_user(session, target_id)
    now = now or utcnow()
    day = kst_date(now)
    if await session.get(Cheer, (me.id, target.id, day)):
        raise FriendError("오늘은 이미 응원했어요. 내일 또 응원해 주세요.", 409)
    session.add(Cheer(sender_id=me.id, receiver_id=target.id, day=day, created_at=now))
    n = await notify(
        session, target.id, "cheer", f"{me.nickname}님이 응원을 보냈어요. 오늘도 같이 읽어요!", None, now
    )
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise FriendError("오늘은 이미 응원했어요. 내일 또 응원해 주세요.", 409) from e
    return n is not None


# ── 프로필 ────────────────────────────────────────────────


@dataclass(slots=True)
class ProfileView:
    user: User
    is_following: bool
    followers: int
    following: int
    books_done: int
    streak: int
    minutes_week: int
    reading: list[tuple[Book, LibraryEntry]] = field(default_factory=list)
    highlights: list[tuple[Highlight, Book]] = field(default_factory=list)


async def minutes_since(session: AsyncSession, user_id: int, since: datetime) -> int:
    ms = await session.scalar(
        select(func.coalesce(func.sum(ReadingEvent.dwell_ms), 0)).where(
            ReadingEvent.user_id == user_id, ReadingEvent.occurred_at >= since
        )
    )
    return int(ms or 0) // 60_000


async def profile(
    session: AsyncSession, viewer: User, user_id: int, now: datetime | None = None
) -> ProfileView:
    now = now or utcnow()
    user = await get_user(session, user_id)
    me = viewer.id == user.id
    follows = not me and await is_following(session, viewer.id, user.id)
    n_followers, n_following = await follow_counts(session, user.id)
    books_done = await session.scalar(
        select(func.count())
        .select_from(LibraryEntry)
        .where(LibraryEntry.user_id == user.id, LibraryEntry.shelf == Shelf.DONE)
    )
    reading = [
        (b, e)
        for e, b in (
            await session.execute(
                select(LibraryEntry, Book)
                .join(Book, Book.id == LibraryEntry.book_id)
                .where(LibraryEntry.user_id == user.id, LibraryEntry.shelf == Shelf.READING)
                .order_by(LibraryEntry.updated_at.desc(), LibraryEntry.id.desc())
                .limit(20)
            )
        ).all()
    ]
    # 친구 공개 밑줄은 나를 팔로우한 사람(과 나)에게만 보인다
    highlights: list[tuple[Highlight, Book]] = []
    if me or follows:
        highlights = [
            (h, b)
            for h, b in (
                await session.execute(
                    select(Highlight, Book)
                    .join(Book, Book.id == Highlight.book_id)
                    .where(
                        Highlight.user_id == user.id,
                        Highlight.battle_id.is_(None),
                        Highlight.visibility == "friends",
                    )
                    .order_by(Highlight.id.desc())
                    .limit(PROFILE_HIGHLIGHTS)
                )
            ).all()
        ]
    return ProfileView(
        user=user,
        is_following=follows,
        followers=n_followers,
        following=n_following,
        books_done=int(books_done or 0),
        streak=await points.streak_days(session, user.id, now),
        minutes_week=await minutes_since(session, user.id, kst_week_start(now)),
        reading=reading,
        highlights=highlights,
    )
