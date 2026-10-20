"""읽기 통계 · 배지 API (네이티브 앱)."""

from dataclasses import asdict
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.db.session import get_session
from app.models import User
from app.services import stats as stats_service

router = APIRouter(prefix="/api/v1/me", tags=["stats"])


class DayOut(BaseModel):
    date: date
    minutes: int
    chunks: int


class HeatOut(BaseModel):
    date: date
    minutes: int


class StatsOut(BaseModel):
    today_minutes: int
    week: list[DayOut]
    heatmap: list[HeatOut]
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


class BadgeOut(BaseModel):
    code: str
    title: str
    description: str
    icon: str
    earned: bool
    earned_at: datetime | None
    progress: int
    goal: int


@router.get("/stats", response_model=StatsOut)
async def my_stats(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    s = await stats_service.stats(session, user)
    return StatsOut(
        today_minutes=s.today_minutes,
        week=[DayOut(date=d.date, minutes=d.minutes, chunks=d.chunks) for d in s.week],
        heatmap=[HeatOut(date=d.date, minutes=d.minutes) for d in s.heatmap],
        streak=s.streak,
        best_streak=s.best_streak,
        books_done=s.books_done,
        books_done_year=s.books_done_year,
        yearly_goal_books=s.yearly_goal_books,
        daily_goal_minutes=s.daily_goal_minutes,
        total_minutes=s.total_minutes,
        total_chunks=s.total_chunks,
        reactions=s.reactions,
        highlights=s.highlights,
    )


@router.get("/badges", response_model=list[BadgeOut])
async def my_badges(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """처음 달성한 배지는 이때 badge 활동으로 남는다(친구 피드에 뜬다)."""
    return [BadgeOut(**asdict(b)) for b in await stats_service.badges(session, user)]
