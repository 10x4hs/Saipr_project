"""친구 찾기 · 팔로우 · 응원 · 프로필 · 피드 API (네이티브 앱)."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, verify_csrf
from app.api.schemas import (
    ActivityOut,
    BookCard,
    UserMini,
    UserSearchOut,
    book_card,
    user_mini,
)
from app.db.session import get_session
from app.models import User
from app.services import activity, catalog
from app.services import friends as friend_service

router = APIRouter(prefix="/api/v1", tags=["friends"], dependencies=[Depends(verify_csrf)])


class ProfileStatsOut(BaseModel):
    books_done: int
    streak: int
    minutes_week: int


class ReadingCardOut(BookCard):
    progress_pct: int


class ProfileHighlightOut(BaseModel):
    """프로필의 친구 공개 밑줄. 내 위치보다 뒤면(스포일러 가드) quote·note가 null이고 locked=true."""

    id: int
    book: BookCard
    chunk_index: int
    quote: str | None
    note: str | None
    color: str
    locked: bool
    created_at: datetime


class ProfileOut(UserMini):
    bio: str | None
    is_following: bool
    followers: int
    following: int
    stats: ProfileStatsOut
    reading: list[ReadingCardOut]
    highlights: list[ProfileHighlightOut]


class CheerOut(BaseModel):
    # 받는 사람의 하루 알림 상한(5건)에 걸리면 false — 응원 기록은 남는다
    delivered: bool


@router.get("/users/search", response_model=list[UserSearchOut])
async def search_users(
    q: str = Query(min_length=1, max_length=40),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    found = await friend_service.search(session, user, q)
    following = await friend_service.following_set(session, user.id, [u.id for u in found])
    return [UserSearchOut(**user_mini(u).model_dump(), is_following=u.id in following) for u in found]


@router.get("/users/{user_id}", response_model=ProfileOut)
async def get_profile(
    user_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    p = await friend_service.profile(session, user, user_id)
    books = {b.id: b for b, _ in p.reading} | {b.id: b for _, b in p.highlights}
    readers = await catalog.readers_counts(session, books)
    positions = await activity.viewer_positions(session, user, books.values())
    highlights = []
    for h, b in p.highlights:
        data = activity.guard_quote(
            {"quote": h.quote, "note": h.comment, "chunk_index": h.chunk_index},
            user,
            h.user_id,
            positions.get(b.id, -1),
        )
        highlights.append(
            ProfileHighlightOut(
                id=h.id,
                book=book_card(b, readers[b.id]),
                chunk_index=h.chunk_index,
                quote=data["quote"],
                note=data["note"],
                color=h.color,
                locked=data["locked"],
                created_at=h.created_at,
            )
        )
    return ProfileOut(
        **user_mini(p.user).model_dump(),
        bio=p.user.bio,
        is_following=p.is_following,
        followers=p.followers,
        following=p.following,
        stats=ProfileStatsOut(books_done=p.books_done, streak=p.streak, minutes_week=p.minutes_week),
        reading=[
            ReadingCardOut(**book_card(b, readers[b.id]).model_dump(), progress_pct=e.progress_pct)
            for b, e in p.reading
        ],
        highlights=highlights,
    )


@router.post("/users/{user_id}/follow", status_code=204)
async def follow(
    user_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    await friend_service.follow(session, user, user_id)


@router.delete("/users/{user_id}/follow", status_code=204)
async def unfollow(
    user_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    await friend_service.unfollow(session, user, user_id)


@router.post("/users/{user_id}/cheer", response_model=CheerOut, status_code=202)
async def cheer(
    user_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    return CheerOut(delivered=await friend_service.cheer(session, user, user_id))


@router.get("/me/following", response_model=list[UserMini])
async def my_following(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [user_mini(u) for u in await friend_service.following(session, user.id)]


@router.get("/me/followers", response_model=list[UserMini])
async def my_followers(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [user_mini(u) for u in await friend_service.followers(session, user.id)]


@router.get("/feed", response_model=list[ActivityOut])
async def feed(
    before: int | None = Query(None, ge=1),
    limit: int = Query(20, ge=1, le=activity.FEED_MAX),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """내가 팔로우한 사람 + 나의 활동, 새 것부터. 다음 쪽은 마지막 항목의 id를 before로."""
    items = await activity.feed(session, user, before, limit)
    readers = await catalog.readers_counts(session, {i.book.id for i in items if i.book})
    return [
        ActivityOut(
            id=i.activity.id,
            user=user_mini(i.user),
            kind=i.activity.kind,
            book=book_card(i.book, readers[i.book.id]) if i.book else None,
            data=i.data,
            created_at=i.activity.created_at,
        )
        for i in items
    ]
