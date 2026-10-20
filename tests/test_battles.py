"""팀 · 리그 · 페이지 레이스 · 한줄평 배틀 · 포인트 · 알림."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.clock import KST
from app.models import Battle, Notification, PointsLog
from app.services import battles as battle_service
from app.services import notifications as noti
from app.services import teams as team_service
from tests.conftest import make_book, signup
from tests.test_reading import ago, post_events

SMALL = ["가" * 15]  # 최소 체류 0.6초


async def two_teams(api):
    users = {}
    for nick in ("서연", "준호", "도윤", "민지"):
        c = api()
        await signup(c, nick)
        users[nick] = c
    a = (await users["서연"].post("/api/v1/teams", json={"name": "봄봄단"})).json()
    await users["준호"].post(f"/api/v1/teams/join/{a['invite_code']}")
    b = (await users["도윤"].post("/api/v1/teams", json={"name": "동백꽃파"})).json()
    await users["민지"].post(f"/api/v1/teams/join/{b['invite_code']}")
    return users, a, b


def period(days=7):
    now = datetime.now(UTC)
    return {
        "starts_at": (now - timedelta(seconds=30)).isoformat(),
        "ends_at": (now + timedelta(days=days)).isoformat(),
    }


async def test_team_join_and_size_limit(api):
    owner = api()
    await signup(owner, "팀장")
    team = (await owner.post("/api/v1/teams", json={"name": "여섯"})).json()
    for i in range(5):
        c = api()
        await signup(c, f"팀원{i}")
        assert (await c.post(f"/api/v1/teams/join/{team['invite_code']}")).status_code == 200
    late = api()
    await signup(late, "일곱째")
    assert (await late.post(f"/api/v1/teams/join/{team['invite_code']}")).status_code == 409
    mine = (await owner.get("/api/v1/teams")).json()
    assert len(mine[0]["members"]) == 6


async def test_page_race_scores_team_average(api, session_factory):
    book = await make_book(session_factory, [SMALL] * 10)
    users, a, b = await two_teams(api)
    r = await users["서연"].post(
        "/api/v1/battles",
        json={"type": "page_race", "book_id": book, "team_a_id": a["id"], "team_b_id": b["id"], **period()},
    )
    assert r.status_code == 201, r.text
    battle = r.json()

    # 봄봄단: 서연 4 + 준호 0 → 평균 2.0 / 동백꽃파: 도윤 6 + 민지 0 → 평균 3.0 (팀 평균으로 비교)
    await post_events(users["서연"], book, [(i, 1_000, ago(-1 - i * 2)) for i in range(4)])
    await post_events(users["도윤"], book, [(i, 1_000, ago(-1 - i * 2)) for i in range(6)])
    got = (await users["서연"].get(f"/api/v1/battles/{battle['id']}")).json()
    assert (got["team_a"]["total"], got["team_a"]["average"]) == (4, 2.0)
    assert (got["team_b"]["total"], got["team_b"]["average"]) == (6, 3.0)
    assert got["status"] == "active"

    # 기간을 끝내고 정산: 동백꽃파 승리, 팀원당 +100P, 두 번 정산해도 한 번만
    async with session_factory() as s:
        await s.execute(update(Battle).values(ends_at=datetime.now(UTC) + timedelta(seconds=10)))
        await s.commit()
        b_obj = await s.get(Battle, battle["id"])
        later = datetime.now(UTC) + timedelta(seconds=20)
        assert await battle_service.settle(s, b_obj, later) is True
        assert await battle_service.settle(s, b_obj, later) is False
        wins = list(await s.scalars(select(PointsLog).where(PointsLog.source == "battle_win")))
    assert sorted((p.user_id, p.amount) for p in wins) == [(3, 100), (4, 100)]


async def test_page_race_rejects_tracker_book_and_foreign_team(api):
    users, a, b = await two_teams(api)
    tracker = (
        await users["서연"].post(
            "/api/v1/books/track", json={"source": "kakao", "external_id": "k", "title": "상용"}
        )
    ).json()
    body = {
        "type": "page_race",
        "book_id": tracker["book_id"],
        "team_a_id": a["id"],
        "team_b_id": b["id"],
        **period(),
    }
    assert (await users["서연"].post("/api/v1/battles", json=body)).status_code == 400
    # 내가 속하지 않은 팀 이름으로 신청 불가
    body["team_a_id"], body["team_b_id"] = b["id"], a["id"]
    assert (await users["서연"].post("/api/v1/battles", json=body)).status_code == 403


async def test_highlight_battle_voting_rules(api, session_factory):
    book = await make_book(session_factory, [["봄이 왔다. 점순이는 키가 자라지 않는다."]] * 2)
    users, a, b = await two_teams(api)
    battle = (
        await users["서연"].post(
            "/api/v1/battles",
            json={
                "type": "highlight_battle",
                "book_id": book,
                "team_a_id": a["id"],
                "team_b_id": b["id"],
                **period(),
            },
        )
    ).json()
    url = f"/api/v1/battles/{battle['id']}/highlights"

    bad = await users["서연"].post(url, json={"chunk_index": 0, "quote": "본문에 없는 문장"})
    assert bad.status_code == 400
    h1 = (
        await users["서연"].post(
            url, json={"chunk_index": 0, "quote": "점순이는 키가 자라지 않는다.", "comment": "명문"}
        )
    ).json()
    h2 = (await users["도윤"].post(url, json={"chunk_index": 0, "quote": "봄이 왔다."})).json()

    vote = lambda who, hid: users[who].post(f"{url}/{hid}/vote")  # noqa: E731
    assert (await vote("서연", h1["id"])).status_code == 403  # 자기 글
    assert (await vote("준호", h1["id"])).status_code == 204
    assert (await vote("준호", h1["id"])).status_code == 409  # 중복
    assert (await vote("도윤", h1["id"])).status_code == 204
    assert (await vote("서연", h2["id"])).status_code == 204

    listed = (await users["준호"].get(url)).json()
    assert [(h["quote"], h["votes"], h["voted_by_me"]) for h in listed] == [
        ("점순이는 키가 자라지 않는다.", 2, True),
        ("봄이 왔다.", 1, False),
    ]
    async with session_factory() as s:
        b_obj = await s.get(Battle, battle["id"])
        assert await battle_service.winner(s, b_obj) == a["id"]


async def test_vote_limit_is_three(api, session_factory):
    book = await make_book(session_factory, [["하나. 둘. 셋. 넷."]])
    users, a, b = await two_teams(api)
    battle = (
        await users["서연"].post(
            "/api/v1/battles",
            json={
                "type": "highlight_battle",
                "book_id": book,
                "team_a_id": a["id"],
                "team_b_id": b["id"],
                **period(),
            },
        )
    ).json()
    url = f"/api/v1/battles/{battle['id']}/highlights"
    ids = [
        (await users["서연"].post(url, json={"chunk_index": 0, "quote": q})).json()["id"]
        for q in ("하나.", "둘.", "셋.", "넷.")
    ]
    codes = [(await users["도윤"].post(f"{url}/{i}/vote")).status_code for i in ids]
    assert codes == [204, 204, 204, 409]


async def test_weekly_league_groups_and_ranks(api, session_factory):
    book = await make_book(session_factory, [SMALL] * 5)
    users, a, b = await two_teams(api)
    await post_events(users["도윤"], book, [(i, 1_000, ago(-1 - i * 2)) for i in range(2)])
    league = (await users["서연"].get(f"/api/v1/leagues/{a['id']}")).json()
    assert [(r["rank"], r["name"], r["average"]) for r in league] == [
        (1, "동백꽃파", 1.0),
        (2, "봄봄단", 0.0),
    ]

    leagues = team_service.build_leagues(
        [team_service.TeamScore(i, f"t{i}", members=1 + i % 3, total=i) for i in range(25)]
    )
    assert [len(lg) for lg in leagues] == [10, 10, 5]


async def test_challenges_award_once_per_period(api, session_factory):
    book = await make_book(session_factory, [SMALL] * 6)
    c = api()
    await signup(c)
    await post_events(c, book, [(i, 1_000, ago(-1 - i * 2)) for i in range(6)])
    pts = (await c.get("/api/v1/points")).json()
    daily = next(ch for ch in pts["challenges"] if ch["code"] == "daily_5_chunks")
    assert daily["progress"] >= 5
    assert [h["source"] for h in pts["history"]].count("challenge") == 1
    assert pts["balance"] == 6 + 10


def test_quiet_hours():
    def kst(h, m=0):
        return datetime(2026, 10, 20, h, m, tzinfo=KST).astimezone(UTC)

    assert noti.deliver_after(kst(12)) == kst(12)
    assert noti.deliver_after(kst(23)) == datetime(2026, 10, 21, 8, tzinfo=KST).astimezone(UTC)
    assert noti.deliver_after(kst(3)) == kst(8)


async def test_notification_daily_limit(session_factory):
    async with session_factory() as s:
        from app.models import User

        s.add(User(id=1, nickname="u"))
        await s.commit()
        noon = datetime(2026, 10, 20, 12, tzinfo=KST).astimezone(UTC)
        made = [await noti.notify(s, 1, "t", f"알림 {i}", now=noon) for i in range(7)]
        await s.commit()
        assert sum(n is not None for n in made) == 5
        assert len(await noti.inbox(s, 1, noon)) == 5
        assert await noti.unread_count(s, 1, noon) == 5
        await noti.mark_all_read(s, 1, noon)
        assert await noti.unread_count(s, 1, noon) == 0
        assert (await s.scalar(select(Notification.read_at))) is not None


async def test_battle_tick_reminds_and_settles(api, session_factory):
    book = await make_book(session_factory, [SMALL] * 2)
    users, a, b = await two_teams(api)
    now = datetime.now(UTC)
    await users["서연"].post(
        "/api/v1/battles",
        json={
            "type": "page_race",
            "book_id": book,
            "team_a_id": a["id"],
            "team_b_id": b["id"],
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(hours=3)).isoformat(),
        },
    )
    async with session_factory() as s:
        noon = datetime.now(KST).replace(hour=12).astimezone(UTC)
        first = await battle_service.tick(s, noon)
        again = await battle_service.tick(s, noon)
        assert first["reminded"] == 4 and again["reminded"] == 0
        done = await battle_service.tick(s, now + timedelta(hours=4))
        assert done["settled"] == 1


async def test_mark_read_after_loading_inbox_from_db(session_factory):
    """DB에서 읽어온(시간대 없는) 알림이 세션에 있어도 모두 읽음 처리가 동작한다 (/me 화면 회귀)."""
    from app.models import User

    noon = datetime(2026, 10, 20, 12, tzinfo=KST).astimezone(UTC)
    async with session_factory() as s:
        s.add(User(id=1, nickname="u"))
        await s.commit()
        await noti.notify(s, 1, "t", "알림", now=noon)
        await s.commit()
    async with session_factory() as s:
        loaded = await noti.inbox(s, 1, noon)  # 화면처럼 목록을 들고 있는 상태
        await noti.mark_all_read(s, 1, noon)
        assert len(loaded) == 1
        assert await noti.unread_count(s, 1, noon) == 0
