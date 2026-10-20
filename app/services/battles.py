"""팀 대항 배틀 (PRD BTL-01 페이지 레이스, BTL-02 밑줄/한줄평 배틀).

- 페이지 레이스 점수 = 기간 안에 그 책에서 검증된 청크 수의 팀 평균. 트래커 도서는 만들 수 없다.
- 한줄평 배틀: 기간 동안 올린 밑줄+한줄평에 1인 3표, 자기 글 금지, 같은 글 중복 투표는 DB 복합 PK로 차단.
- 종료 후 정산(settle)은 스케줄러가 돌거나 화면을 열 때 한다. 같은 배틀은 한 번만 정산된다.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import aware, utcnow
from app.models import (
    Battle,
    BattleStatus,
    BattleType,
    Book,
    BookChunk,
    Highlight,
    HighlightVote,
    Team,
    User,
)
from app.services import library, points, teams
from app.services.notifications import already_notified, notify

VOTES_PER_USER = 3
MAX_DURATION = timedelta(days=31)
ENDING_SOON = timedelta(hours=24)


class BattleError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(slots=True)
class TeamSide:
    team_id: int
    name: str
    members: list[tuple[int, str, int]] = field(default_factory=list)  # (user_id, nickname, chunks)

    @property
    def total(self) -> int:
        return sum(c for _, _, c in self.members)

    @property
    def average(self) -> float:
        return round(self.total / len(self.members), 2) if self.members else 0.0


@dataclass(slots=True)
class HighlightView:
    id: int
    user_id: int
    nickname: str
    team_id: int | None
    chunk_index: int
    quote: str
    comment: str | None
    votes: int
    voted_by_me: bool


def status_at(battle: Battle, now: datetime) -> BattleStatus:
    if battle.status is BattleStatus.FINISHED or now >= aware(battle.ends_at):
        return BattleStatus.FINISHED
    if now >= aware(battle.starts_at):
        return BattleStatus.ACTIVE
    return BattleStatus.SCHEDULED


async def create_battle(
    session: AsyncSession,
    creator: User,
    type: BattleType,
    book: Book,
    team_a: Team,
    team_b: Team,
    starts_at: datetime,
    ends_at: datetime,
) -> Battle:
    if team_a.id == team_b.id:
        raise BattleError("서로 다른 두 팀이 필요해요.")
    if creator.id not in await teams.member_ids(session, team_a.id):
        raise BattleError("내가 속한 팀으로만 배틀을 신청할 수 있어요.", 403)
    if type is BattleType.PAGE_RACE and not book.has_fulltext:
        # 트래커 도서는 검증할 수 없으므로 레이스 대상이 아니다 (PRD READ-02)
        raise BattleError("페이지 레이스는 앱 안에서 읽을 수 있는 책으로만 할 수 있어요.")
    starts_at, ends_at = aware(starts_at), aware(ends_at)
    if not starts_at < ends_at or ends_at - starts_at > MAX_DURATION:
        raise BattleError("기간은 시작보다 끝이 늦고, 최대 31일이에요.")
    a_ids = set(await teams.member_ids(session, team_a.id))
    b_ids = set(await teams.member_ids(session, team_b.id))
    if len(a_ids) < teams.MIN_TEAM_FOR_BATTLE or len(b_ids) < teams.MIN_TEAM_FOR_BATTLE:
        raise BattleError(f"두 팀 모두 {teams.MIN_TEAM_FOR_BATTLE}명 이상이어야 배틀을 할 수 있어요.")
    if a_ids & b_ids:
        # 양쪽에 다 속한 사람은 두 팀 점수에 모두 잡힌다
        raise BattleError("두 팀에 모두 속한 사람이 있으면 배틀을 할 수 없어요.")
    battle = Battle(
        type=type,
        book_id=book.id,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        status=BattleStatus.SCHEDULED,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    session.add(battle)
    await session.flush()
    for uid in await teams.member_ids(session, team_b.id):
        await notify(
            session,
            uid,
            "battle",
            f"팀 「{team_a.name}」이 「{book.title}」 배틀을 걸어왔어요!",
            f"/battles/{battle.id}",
        )
    await session.commit()
    return battle


async def sides(session: AsyncSession, battle: Battle) -> tuple[TeamSide, TeamSide]:
    out = []
    for tid in (battle.team_a_id, battle.team_b_id):
        team = await session.get(Team, tid)
        users = await teams.members(session, tid)
        counts = await teams.verified_counts(
            session, [u.id for u in users], aware(battle.starts_at), aware(battle.ends_at), battle.book_id
        )
        out.append(
            TeamSide(tid, team.name if team else "?", [(u.id, u.nickname, counts[u.id]) for u in users])
        )
    return out[0], out[1]


async def _team_of(session: AsyncSession, battle: Battle, user_id: int) -> int | None:
    for tid in (battle.team_a_id, battle.team_b_id):
        if user_id in await teams.member_ids(session, tid):
            return tid
    return None


async def add_highlight(
    session: AsyncSession,
    battle: Battle,
    user: User,
    chunk_index: int,
    quote: str,
    comment: str | None,
    now: datetime | None = None,
) -> Highlight:
    now = now or utcnow()
    if battle.type is not BattleType.HIGHLIGHT_BATTLE:
        raise BattleError("한줄평 배틀에서만 밑줄을 올릴 수 있어요.")
    if status_at(battle, now) is not BattleStatus.ACTIVE:
        raise BattleError("진행 중인 배틀이 아니에요.", 409)
    if await _team_of(session, battle, user.id) is None:
        raise BattleError("배틀에 참가한 팀원만 올릴 수 있어요.", 403)
    book = await session.get(Book, battle.book_id)
    quote = " ".join(quote.split())
    if not 1 <= len(quote) <= 500:
        raise BattleError("밑줄 문장은 1~500자예요.")
    if comment is not None:
        comment = comment.strip()[:280] or None
    if book and book.has_fulltext:
        entry = await library.get_entry(session, user.id, book.id)
        if chunk_index > library.position_of(entry, book) + 1:
            raise BattleError("아직 읽지 않은 위치예요.", 403)
        text = await session.scalar(
            select(BookChunk.text).where(BookChunk.book_id == book.id, BookChunk.chunk_index == chunk_index)
        )
        if text is None or quote not in " ".join(text.split()):
            raise BattleError("밑줄 문장이 본문에 없어요.")
    h = Highlight(
        user_id=user.id,
        book_id=battle.book_id,
        battle_id=battle.id,
        chunk_index=chunk_index,
        anchor=0,
        quote=quote,
        comment=comment,
        created_at=now,
    )
    session.add(h)
    await session.commit()
    return h


async def vote(
    session: AsyncSession, battle: Battle, highlight_id: int, user: User, now: datetime | None = None
) -> None:
    now = now or utcnow()
    if status_at(battle, now) is not BattleStatus.ACTIVE:
        raise BattleError("진행 중인 배틀이 아니에요.", 409)
    h = await session.get(Highlight, highlight_id)
    if h is None or h.battle_id != battle.id:
        raise BattleError("밑줄을 찾을 수 없어요.", 404)
    if h.user_id == user.id:
        raise BattleError("내 글에는 투표할 수 없어요.", 403)
    if await _team_of(session, battle, user.id) is None:
        raise BattleError("배틀에 참가한 팀원만 투표할 수 있어요.", 403)
    used = await session.scalar(
        select(func.count())
        .select_from(HighlightVote)
        .join(Highlight, Highlight.id == HighlightVote.highlight_id)
        .where(Highlight.battle_id == battle.id, HighlightVote.user_id == user.id)
    )
    if (used or 0) >= VOTES_PER_USER:
        raise BattleError(f"한 배틀에서 최대 {VOTES_PER_USER}표까지예요.", 409)
    session.add(HighlightVote(highlight_id=h.id, user_id=user.id))
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise BattleError("이미 투표한 글이에요.", 409) from e


async def highlights(session: AsyncSession, battle: Battle, viewer_id: int) -> list[HighlightView]:
    votes = func.count(HighlightVote.user_id).label("votes")
    rows = await session.execute(
        select(Highlight, User.nickname, votes)
        .join(User, User.id == Highlight.user_id)
        .outerjoin(HighlightVote, HighlightVote.highlight_id == Highlight.id)
        .where(Highlight.battle_id == battle.id)
        .group_by(Highlight.id, User.nickname)
        .order_by(votes.desc(), Highlight.id)
    )
    mine = set(
        await session.scalars(
            select(HighlightVote.highlight_id)
            .join(Highlight, Highlight.id == HighlightVote.highlight_id)
            .where(Highlight.battle_id == battle.id, HighlightVote.user_id == viewer_id)
        )
    )
    a_ids = set(await teams.member_ids(session, battle.team_a_id))
    b_ids = set(await teams.member_ids(session, battle.team_b_id))
    out = []
    for h, nick, n in rows.all():
        team_id = battle.team_a_id if h.user_id in a_ids else battle.team_b_id if h.user_id in b_ids else None
        out.append(
            HighlightView(h.id, h.user_id, nick, team_id, h.chunk_index, h.quote, h.comment, n, h.id in mine)
        )
    return out


async def winner(session: AsyncSession, battle: Battle) -> int | None:
    """승리 팀 id. 동점이면 None."""
    if battle.type is BattleType.PAGE_RACE:
        a, b = await sides(session, battle)
        if a.average == b.average:
            return None
        return a.team_id if a.average > b.average else b.team_id
    hs = [h for h in await highlights(session, battle, viewer_id=0) if h.team_id is not None]
    if not hs or (len(hs) > 1 and hs[0].votes == hs[1].votes) or hs[0].votes == 0:
        return None
    return hs[0].team_id


async def settle(session: AsyncSession, battle: Battle, now: datetime | None = None) -> bool:
    """끝난 배틀을 한 번만 정산한다. 승리 팀원 각자 +100P (ref_id로 중복 지급 방지)."""
    now = now or utcnow()
    if battle.status is BattleStatus.FINISHED or status_at(battle, now) is not BattleStatus.FINISHED:
        return False
    win = await winner(session, battle)
    # 스케줄러와 화면 열기가 동시에 정산해도 한쪽만 지급하도록, 상태를 조건부로 먼저 바꾼다
    claimed = await session.execute(
        update(Battle)
        .where(Battle.id == battle.id, Battle.status != BattleStatus.FINISHED)
        .values(status=BattleStatus.FINISHED)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        await session.rollback()
        await session.refresh(battle)
        return False
    book = await session.get(Book, battle.book_id)
    title = book.title if book else "책"
    for tid in (battle.team_a_id, battle.team_b_id):
        for uid in await teams.member_ids(session, tid):
            if win == tid:
                await points.award(
                    session, uid, "battle_win", points.BATTLE_WIN_POINTS, f"battle:{battle.id}", now
                )
                msg = f"「{title}」 배틀에서 이겼어요! (+{points.BATTLE_WIN_POINTS}P)"
            elif win is None:
                msg = f"「{title}」 배틀이 무승부로 끝났어요."
            else:
                msg = f"「{title}」 배틀이 끝났어요. 다음엔 이겨봐요!"
            await notify(session, uid, "battle_result", msg, f"/battles/{battle.id}", now)
    battle.status = BattleStatus.FINISHED
    try:
        await session.commit()
    except IntegrityError:
        # 포인트 원장의 UNIQUE가 중복 지급을 막았다 — 다른 쪽이 이미 정산했다
        await session.rollback()
        await session.refresh(battle)
        return False
    return True


async def is_participant(session: AsyncSession, battle: Battle, user_id: int) -> bool:
    return await _team_of(session, battle, user_id) is not None


async def tick(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """스케줄러가 주기적으로 부른다: 상태 갱신, 종료 24시간 전 알림, 끝난 배틀 정산."""
    now = now or utcnow()
    settled = reminded = 0
    open_battles = list(await session.scalars(select(Battle).where(Battle.status != BattleStatus.FINISHED)))
    for b in open_battles:
        st = status_at(b, now)
        if st is BattleStatus.FINISHED:
            settled += await settle(session, b, now)
            continue
        if st is BattleStatus.ACTIVE and b.status is BattleStatus.SCHEDULED:
            b.status = BattleStatus.ACTIVE
        if st is BattleStatus.ACTIVE and aware(b.ends_at) - now <= ENDING_SOON:
            link = f"/battles/{b.id}"
            for tid in (b.team_a_id, b.team_b_id):
                for uid in await teams.member_ids(session, tid):
                    if not await already_notified(session, uid, "battle_ending", link):
                        await notify(
                            session, uid, "battle_ending", "배틀 종료까지 24시간도 안 남았어요!", link, now
                        )
                        reminded += 1
        await session.commit()
    return {"settled": settled, "reminded": reminded}


async def battles_of(session: AsyncSession, user_id: int) -> list[Battle]:
    team_ids = [t.id for t in await teams.teams_of(session, user_id)]
    if not team_ids:
        return []
    return list(
        await session.scalars(
            select(Battle)
            .where(Battle.team_a_id.in_(team_ids) | Battle.team_b_id.in_(team_ids))
            .order_by(Battle.ends_at.desc())
        )
    )
