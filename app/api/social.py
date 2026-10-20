"""팀 · 배틀 · 포인트 · 알림 API (Phase 4~6)."""

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, verify_csrf
from app.core.clock import utcnow
from app.db.session import get_session
from app.models import Battle, BattleStatus, BattleType, Book, Team, User
from app.services import battles as battle_service
from app.services import notifications as noti
from app.services import points as point_service
from app.services import teams as team_service

router = APIRouter(prefix="/api/v1", tags=["social"], dependencies=[Depends(verify_csrf)])


# ── 팀 · 리그 ─────────────────────────────────────────────


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class TeamOut(BaseModel):
    id: int
    name: str
    invite_code: str | None
    members: list[str]


class LeagueRowOut(BaseModel):
    rank: int
    team_id: int
    name: str
    members: int
    total: int
    average: float


async def team_out(session: AsyncSession, team: Team, viewer: User) -> TeamOut:
    users = await team_service.members(session, team.id)
    is_member = any(u.id == viewer.id for u in users)
    return TeamOut(
        id=team.id,
        name=team.name,
        invite_code=team.invite_code if is_member else None,
        members=[u.nickname for u in users],
    )


@router.post("/teams", response_model=TeamOut, status_code=201)
async def create_team(
    body: TeamIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    return await team_out(session, await team_service.create_team(session, user, body.name), user)


@router.get("/teams", response_model=list[TeamOut])
async def my_teams(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [await team_out(session, t, user) for t in await team_service.teams_of(session, user.id)]


@router.post("/teams/join/{code}", response_model=TeamOut)
async def join_team(
    code: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    return await team_out(session, await team_service.join_team(session, code, user), user)


@router.post("/teams/{team_id}/leave", status_code=204)
async def leave_team(
    team_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "팀을 찾을 수 없어요.")
    await team_service.leave_team(session, team, user)


@router.get("/leagues/{team_id}", response_model=list[LeagueRowOut])
async def league(
    team_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    rows = await team_service.league_of(session, team_id)
    if not rows:
        raise HTTPException(404, "팀을 찾을 수 없어요.")
    return [
        LeagueRowOut(
            rank=i + 1, team_id=s.team_id, name=s.name, members=s.members, total=s.total, average=s.average
        )
        for i, s in enumerate(rows)
    ]


# ── 배틀 ─────────────────────────────────────────────────


class BattleIn(BaseModel):
    type: BattleType
    book_id: int
    team_a_id: int
    team_b_id: int
    starts_at: datetime
    ends_at: datetime


class SideOut(BaseModel):
    team_id: int
    name: str
    total: int
    average: float
    members: list[dict]


class BattleOut(BaseModel):
    id: int
    type: BattleType
    book_id: int
    book_title: str
    status: BattleStatus
    starts_at: datetime
    ends_at: datetime
    team_a: SideOut
    team_b: SideOut


class HighlightIn(BaseModel):
    chunk_index: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=500)
    comment: str | None = Field(None, max_length=280)


class HighlightOut(BaseModel):
    id: int
    user_id: int
    nickname: str
    team_id: int | None
    chunk_index: int
    quote: str
    comment: str | None
    votes: int
    voted_by_me: bool


def side_out(s: battle_service.TeamSide) -> SideOut:
    return SideOut(
        team_id=s.team_id,
        name=s.name,
        total=s.total,
        average=s.average,
        members=[{"user_id": u, "nickname": n, "chunks": c} for u, n, c in s.members],
    )


async def battle_out(session: AsyncSession, b: Battle) -> BattleOut:
    book = await session.get(Book, b.book_id)
    a, bb = await battle_service.sides(session, b)
    return BattleOut(
        id=b.id,
        type=b.type,
        book_id=b.book_id,
        book_title=book.title if book else "?",
        status=battle_service.status_at(b, utcnow()),
        starts_at=b.starts_at,
        ends_at=b.ends_at,
        team_a=side_out(a),
        team_b=side_out(bb),
    )


async def load_battle(battle_id: int, session: AsyncSession, user: User) -> Battle:
    b = await session.get(Battle, battle_id)
    # 밑줄은 스포일러가 될 수 있어 두 팀 팀원만 본다
    if b is None or not await battle_service.is_participant(session, b, user.id):
        raise HTTPException(404, "배틀을 찾을 수 없어요.")
    # 화면을 열었을 때 이미 끝났으면 그 자리에서 정산한다 (스케줄러가 꺼져 있어도 결과가 나오도록)
    await battle_service.settle(session, b)
    return b


@router.post("/battles", response_model=BattleOut, status_code=201)
async def create_battle(
    body: BattleIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    book = await session.get(Book, body.book_id)
    team_a = await session.get(Team, body.team_a_id)
    team_b = await session.get(Team, body.team_b_id)
    if not (book and team_a and team_b):
        raise HTTPException(404, "책 또는 팀을 찾을 수 없어요.")
    b = await battle_service.create_battle(
        session, user, body.type, book, team_a, team_b, body.starts_at, body.ends_at
    )
    return await battle_out(session, b)


@router.get("/battles", response_model=list[BattleOut])
async def my_battles(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [await battle_out(session, b) for b in await battle_service.battles_of(session, user.id)]


@router.get("/battles/{battle_id}", response_model=BattleOut)
async def get_battle(
    battle_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    return await battle_out(session, await load_battle(battle_id, session, user))


@router.get("/battles/{battle_id}/highlights", response_model=list[HighlightOut])
async def list_highlights(
    battle_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    b = await load_battle(battle_id, session, user)
    return [HighlightOut(**asdict(h)) for h in await battle_service.highlights(session, b, user.id)]


@router.post("/battles/{battle_id}/highlights", status_code=201)
async def add_highlight(
    battle_id: int,
    body: HighlightIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    b = await load_battle(battle_id, session, user)
    h = await battle_service.add_highlight(session, b, user, body.chunk_index, body.quote, body.comment)
    return {"id": h.id}


@router.post("/battles/{battle_id}/highlights/{highlight_id}/vote", status_code=204)
async def vote(
    battle_id: int,
    highlight_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    await battle_service.vote(session, await load_battle(battle_id, session, user), highlight_id, user)


# ── 포인트 · 챌린지 ─────────────────────────────────────────


class PointsOut(BaseModel):
    balance: int
    history: list[dict]
    challenges: list[dict]


@router.get("/points", response_model=PointsOut)
async def my_points(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    now = utcnow()
    return PointsOut(
        balance=await point_service.balance(session, user.id),
        history=[
            {"source": p.source, "amount": p.amount, "ref_id": p.ref_id, "created_at": p.created_at}
            for p in await point_service.history(session, user.id)
        ],
        challenges=[
            {
                "code": c.code,
                "title": c.title,
                "reward_points": c.reward_points,
                "progress": await point_service.progress_of(session, user.id, c, now),
                "goal": point_service.goal_of(c),
            }
            for c in point_service.CHALLENGES
        ],
    )


# ── 알림 ─────────────────────────────────────────────────


class NotificationOut(BaseModel):
    id: int
    kind: str
    body: str
    link: str | None
    read: bool
    created_at: datetime


@router.get("/notifications", response_model=list[NotificationOut])
async def my_notifications(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [
        NotificationOut(
            id=n.id,
            kind=n.kind,
            body=n.body,
            link=n.link,
            read=n.read_at is not None,
            created_at=n.created_at,
        )
        for n in await noti.inbox(session, user.id)
    ]


@router.post("/notifications/read", status_code=204)
async def read_all(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await noti.mark_all_read(session, user.id)
