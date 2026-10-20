"""팀 · 주간 리그 (PRD TEAM-01).

- 팀 2~6명(만들 때는 1명, 초대 코드로 최대 6명까지).
- 주간 점수 = 이번 주(월 00:00 KST~) 팀원이 검증한 청크 수의 팀 평균. 인원이 적은 팀도 불리하지 않게.
- 리그: 인원이 비슷한 팀끼리 10팀씩 묶는다(Duolingo 리그 모델). 리셋 작업 없이 주 시작 시각으로 계산한다.
  PRD의 Redis Sorted Set은 단일 인스턴스 MVP에서 DB 집계로 대체 — 같은 결과를 돌려준다.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import kst_week_start, utcnow
from app.models import Battle, BattleStatus, ReadingEvent, Team, TeamMember, User
from app.services.notifications import notify

MAX_TEAM = 6
MIN_TEAM_FOR_BATTLE = 2
LEAGUE_SIZE = 10


class TeamError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(slots=True)
class TeamScore:
    team_id: int
    name: str
    members: int
    total: int

    @property
    def average(self) -> float:
        return round(self.total / self.members, 2) if self.members else 0.0


async def create_team(session: AsyncSession, user: User, name: str) -> Team:
    name = name.strip()
    if not 1 <= len(name) <= 40:
        raise TeamError("팀 이름은 1~40자로 정해 주세요.")
    team = Team(name=name, created_by=user.id, invite_code=secrets.token_urlsafe(6))
    session.add(team)
    await session.flush()
    session.add(TeamMember(team_id=team.id, user_id=user.id))
    await session.commit()
    return team


async def member_ids(session: AsyncSession, team_id: int) -> list[int]:
    return list(await session.scalars(select(TeamMember.user_id).where(TeamMember.team_id == team_id)))


async def members(session: AsyncSession, team_id: int) -> list[User]:
    return list(
        await session.scalars(
            select(User)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team_id)
            .order_by(User.id)
        )
    )


async def join_team(session: AsyncSession, code: str, user: User) -> Team:
    team = await session.scalar(select(Team).where(Team.invite_code == code))
    if team is None:
        raise TeamError("팀 초대 코드를 찾을 수 없어요.", 404)
    ids = await member_ids(session, team.id)
    if user.id in ids:
        return team
    if await has_open_battle(session, team.id):
        raise TeamError("배틀이 끝날 때까지는 팀원을 바꿀 수 없어요.", 409)
    if len(ids) >= MAX_TEAM:
        raise TeamError(f"팀이 가득 찼어요 (최대 {MAX_TEAM}명).", 409)
    session.add(TeamMember(team_id=team.id, user_id=user.id))
    await notify(
        session,
        team.created_by,
        "team_joined",
        f"{user.nickname}님이 팀 「{team.name}」에 들어왔어요.",
        f"/teams/{team.id}",
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
    return team


async def leave_team(session: AsyncSession, team: Team, user: User) -> None:
    m = await session.get(TeamMember, (team.id, user.id))
    if m is None:
        raise TeamError("이 팀의 멤버가 아니에요.", 404)
    if await has_open_battle(session, team.id):
        # 나가면 그 사람 점수가 빠져 진행 중이거나 끝난 배틀 결과가 바뀐다
        raise TeamError("배틀이 끝날 때까지는 팀을 나갈 수 없어요.", 409)
    await session.delete(m)
    await session.commit()


async def has_open_battle(session: AsyncSession, team_id: int) -> bool:
    """예정·진행 중이거나 아직 정산 전인 배틀이 있는가. 그동안은 팀원 구성을 고정한다."""
    return bool(
        await session.scalar(
            select(Battle.id).where(
                (Battle.team_a_id == team_id) | (Battle.team_b_id == team_id),
                Battle.status != BattleStatus.FINISHED,
            ).limit(1)
        )
    )


async def teams_of(session: AsyncSession, user_id: int) -> list[Team]:
    return list(
        await session.scalars(
            select(Team)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == user_id)
            .order_by(Team.id)
        )
    )


async def verified_counts(
    session: AsyncSession,
    user_ids: list[int],
    since: datetime,
    until: datetime | None = None,
    book_id: int | None = None,
) -> dict[int, int]:
    """기간 안에 검증된(레이스 인정) 청크 수. 트래커 도서는 이벤트가 없으므로 자연히 빠진다."""
    if not user_ids:
        return {}
    cond = [
        ReadingEvent.user_id.in_(user_ids),
        ReadingEvent.verified,
        ReadingEvent.race_eligible,
        ReadingEvent.occurred_at >= since,
    ]
    if until is not None:
        cond.append(ReadingEvent.occurred_at < until)
    if book_id is not None:
        cond.append(ReadingEvent.book_id == book_id)
    rows = await session.execute(
        select(ReadingEvent.user_id, func.count()).where(*cond).group_by(ReadingEvent.user_id)
    )
    counts = {uid: 0 for uid in user_ids}
    counts.update({uid: n for uid, n in rows.all()})
    return counts


async def weekly_scores(session: AsyncSession, now: datetime | None = None) -> list[TeamScore]:
    now = now or utcnow()
    since = kst_week_start(now)
    team_rows = (await session.execute(select(Team.id, Team.name))).all()
    links = (await session.execute(select(TeamMember.team_id, TeamMember.user_id))).all()
    by_team: dict[int, list[int]] = {tid: [] for tid, _ in team_rows}
    for tid, uid in links:
        by_team.setdefault(tid, []).append(uid)
    counts = await verified_counts(session, sorted({uid for _, uid in links}), since)
    return [
        TeamScore(tid, name, len(by_team[tid]), sum(counts.get(u, 0) for u in by_team[tid]))
        for tid, name in team_rows
    ]


def build_leagues(scores: list[TeamScore], size: int = LEAGUE_SIZE) -> list[list[TeamScore]]:
    """인원수가 비슷한 팀끼리 묶고, 리그 안에서는 평균 점수 → 합계 → id 순으로 순위."""
    ordered = sorted(scores, key=lambda s: (s.members, s.team_id))
    leagues = [ordered[i : i + size] for i in range(0, len(ordered), size)]
    return [sorted(lg, key=lambda s: (-s.average, -s.total, s.team_id)) for lg in leagues]


async def league_of(session: AsyncSession, team_id: int, now: datetime | None = None) -> list[TeamScore]:
    for league in build_leagues(await weekly_scores(session, now)):
        if any(s.team_id == team_id for s in league):
            return league
    return []
