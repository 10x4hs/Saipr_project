"""점수·포인트 무결성 회귀 테스트 — 코드 리뷰에서 찾은 우회 경로가 다시 열리지 않게 막는다."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.clock import aware
from app.models import Battle, Book, OAuthAccount, PointsLog, ReadingEvent, Room, User
from app.services import auth as auth_service
from app.services import battles as battle_service
from app.services import reading
from app.services import teams as team_service
from tests.conftest import age_accounts, make_book, signup
from tests.test_battles import period, two_teams
from tests.test_reading import CHUNK, MIN_MS, ago, post_events

T0 = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)


async def reader(session_factory, chunks: int, created: datetime) -> tuple[int, int]:
    book_id = await make_book(session_factory, [CHUNK] * chunks)
    async with session_factory() as s:
        u = User(nickname="읽는이", created_at=created)
        s.add(u)
        await s.commit()
        return u.id, book_id


async def record(session_factory, uid, book_id, events, now):
    async with session_factory() as s:
        user, book = await s.get(User, uid), await s.get(Book, book_id)
        return await reading.record_events(
            s, user, book, [reading.EventIn(i, d, at) for i, d, at in events], now=now
        )


# ── 1. 체류시간: 서버 시계 기준 예산 ─────────────────────────


async def test_cannot_fabricate_a_day_of_reading_after_a_break(session_factory):
    """23시간 쉬었다가 '지난 하루 동안 1분씩 읽었다'는 이벤트를 한꺼번에 보내도 레이스 점수가 되지 않는다."""
    uid, book = await reader(session_factory, 49, created=T0 - timedelta(days=30))
    first = await record(session_factory, uid, book, [(0, MIN_MS, T0)], now=T0)
    assert first.newly_verified == [0]

    later = T0 + timedelta(hours=23)
    forged = [(i, MIN_MS + 1, T0 + timedelta(minutes=i)) for i in range(1, 49)]
    await record(session_factory, uid, book, forged, now=later)
    async with session_factory() as s:
        eligible = await s.scalar(
            select(func.count())
            .select_from(ReadingEvent)
            .where(ReadingEvent.user_id == uid, ReadingEvent.verified, ReadingEvent.race_eligible)
        )
    assert eligible == 1  # 첫 청크만 실시간으로 도착했다


async def test_batch_credit_cannot_exceed_server_elapsed_time(session_factory):
    uid, book = await reader(session_factory, 10, created=T0 - timedelta(days=1))
    await record(session_factory, uid, book, [(0, 1_000, T0)], now=T0)
    # 서버 기준 2분이 지났는데 10분어치(청크 10개)를 읽었다고 주장
    now = T0 + timedelta(minutes=2)
    claim = [(i, MIN_MS + 1, T0 + timedelta(seconds=12 * i)) for i in range(1, 10)]
    await record(session_factory, uid, book, claim, now=now)
    async with session_factory() as s:
        total = await s.scalar(
            select(func.sum(ReadingEvent.dwell_ms)).where(
                ReadingEvent.user_id == uid, ReadingEvent.received_at == now
            )
        )
    assert total <= (2 * 60 + 30) * 1000


async def test_events_backdated_before_last_sync_get_no_credit(session_factory):
    uid, book = await reader(session_factory, 3, created=T0 - timedelta(days=1))
    await record(session_factory, uid, book, [(0, 1_000, T0)], now=T0)
    r = await record(
        session_factory, uid, book, [(1, MIN_MS + 1, T0 - timedelta(hours=1))], now=T0 + timedelta(hours=2)
    )
    assert r.newly_verified == []


async def test_brand_new_account_cannot_claim_long_reading(api, session_factory):
    book = await make_book(session_factory, [CHUNK] * 3)
    async with api() as c:
        await signup(c)  # 방금 가입 → 예산은 30초 남짓
        r = await post_events(c, book, [(0, MIN_MS + 1, ago(1))])
    assert r["newly_verified"] == []


async def test_verified_once_is_enforced_by_db(session_factory):
    uid, book = await reader(session_factory, 1, created=T0)
    async with session_factory() as s:
        for _ in range(2):
            s.add(
                ReadingEvent(
                    user_id=uid, book_id=book, chunk_index=0, dwell_ms=1, verified=True, occurred_at=T0
                )
            )
        with pytest.raises(IntegrityError):
            await s.commit()


# ── 2. 완독 포인트 ────────────────────────────────────────


async def test_tracker_books_cannot_farm_completion_points(api):
    async with api() as c:
        await signup(c)
        for i in range(3):
            book = (
                await c.post(
                    "/api/v1/books/track",
                    json={"source": "kakao", "external_id": f"fake{i}", "title": "가짜"},
                )
            ).json()
            r = await c.put(f"/api/v1/library/{book['book_id']}", json={"shelf": "done"})
            assert r.json()["shelf"] == "done" and r.json()["progress_pct"] == 100
        assert (await c.get("/api/v1/points")).json()["balance"] == 0


async def test_unfinished_fulltext_book_gives_no_completion_points(api, session_factory):
    book = await make_book(session_factory, [CHUNK] * 3)
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        await post_events(c, book, [(0, MIN_MS, ago(100))])  # 3청크 중 1개만
        r = await c.put(f"/api/v1/library/{book}", json={"shelf": "done"})
        assert r.json()["shelf"] == "done" and r.json()["progress_pct"] == 33  # 진행률을 100으로 꾸미지 않음
        history = (await c.get("/api/v1/points")).json()["history"]
    assert "complete" not in [h["source"] for h in history]


async def test_web_track_rejects_unknown_source(api):
    from tests.test_web import HTML, csrf_of, web_signup

    async with api() as c:
        await web_signup(c, "트래커")
        page = await c.get("/search", headers=HTML)
        r = await c.post(
            "/books/track",
            data={"source": "made-up", "external_id": "x", "title": "x", "csrf_token": csrf_of(page.text)},
        )
        assert r.status_code == 303  # 오류 안내와 함께 되돌아감
        assert (await c.get("/api/v1/library")).json() == []


async def test_points_ref_unique_in_db(session_factory):
    async with session_factory() as s:
        s.add(User(id=1, nickname="u"))
        await s.commit()
        for _ in range(2):
            s.add(PointsLog(user_id=1, source="complete", amount=50, ref_id="book:1"))
        with pytest.raises(IntegrityError):
            await s.commit()


# ── 3·5. 배틀 정산 · 팀 고정 ──────────────────────────────


async def test_concurrent_settle_pays_once(api, session_factory):
    book = await make_book(session_factory, [["가" * 15]] * 3)
    users, a, b = await two_teams(api)
    battle = (
        await users["서연"].post(
            "/api/v1/battles",
            json={
                "type": "page_race",
                "book_id": book,
                "team_a_id": a["id"],
                "team_b_id": b["id"],
                **period(),
            },
        )
    ).json()
    await post_events(users["서연"], book, [(0, 1_000, ago(-1))])
    async with session_factory() as s:
        await s.execute(update(Battle).values(ends_at=datetime.now(UTC) + timedelta(seconds=5)))
        await s.commit()
    later = datetime.now(UTC) + timedelta(seconds=10)
    async with session_factory() as s1, session_factory() as s2:
        b1, b2 = await s1.get(Battle, battle["id"]), await s2.get(Battle, battle["id"])
        results = [await battle_service.settle(s1, b1, later), await battle_service.settle(s2, b2, later)]
    assert sorted(results) == [False, True]
    async with session_factory() as s:
        wins = await s.scalar(
            select(func.count()).select_from(PointsLog).where(PointsLog.source == "battle_win")
        )
    assert wins == 2  # 봄봄단 2명 × 1회


async def test_team_roster_locked_during_battle(api, session_factory):
    book = await make_book(session_factory, [["가" * 15]])
    users, a, b = await two_teams(api)
    await users["서연"].post(
        "/api/v1/battles",
        json={"type": "page_race", "book_id": book, "team_a_id": a["id"], "team_b_id": b["id"], **period()},
    )
    late = api()
    await signup(late, "막차")
    assert (await late.post(f"/api/v1/teams/join/{a['invite_code']}")).status_code == 409
    assert (await users["준호"].post(f"/api/v1/teams/{a['id']}/leave")).status_code == 409


async def test_battle_needs_two_full_distinct_teams(api, session_factory):
    book = await make_book(session_factory, [["가" * 15]])
    users, a, b = await two_teams(api)
    solo = (await users["서연"].post("/api/v1/teams", json={"name": "혼자"})).json()
    body = {"type": "page_race", "book_id": book, "team_a_id": solo["id"], "team_b_id": b["id"], **period()}
    assert (await users["서연"].post("/api/v1/battles", json=body)).status_code == 400
    # 서연이 상대 팀에도 들어가 있으면 양쪽 점수에 잡히므로 금지
    await users["서연"].post(f"/api/v1/teams/join/{b['invite_code']}")
    body["team_a_id"] = a["id"]
    assert (await users["서연"].post("/api/v1/battles", json=body)).status_code == 400


async def test_battle_hidden_from_outsiders(api, session_factory):
    book = await make_book(session_factory, [["가" * 15]])
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
    outsider = api()
    await signup(outsider, "구경꾼")
    assert (await outsider.get(f"/api/v1/battles/{battle['id']}")).status_code == 404
    assert (await outsider.get(f"/api/v1/battles/{battle['id']}/highlights")).status_code == 404
    assert (
        await outsider.get(f"/battles/{battle['id']}", headers={"accept": "text/html"})
    ).status_code == 404


# ── 6. 시간대 ───────────────────────────────────────────


def test_aware_normalizes_offsets_to_utc():
    kst_noon = datetime(2026, 10, 20, 12, tzinfo=timezone(timedelta(hours=9)))
    assert aware(kst_noon) == datetime(2026, 10, 20, 3, tzinfo=UTC)
    assert aware(kst_noon).utcoffset() == timedelta(0)
    assert aware(datetime(2026, 10, 20, 3)).tzinfo is UTC


async def test_room_end_with_offset_round_trips(api, session_factory):
    book = await make_book(session_factory, [CHUNK])
    async with api() as c:
        await signup(c)
        r = await c.post(
            "/api/v1/rooms", json={"book_id": book, "name": "마감", "ends_at": "2026-11-01T23:59:00+09:00"}
        )
        room_id = r.json()["id"]
    async with session_factory() as s:
        stored = (await s.get(Room, room_id)).ends_at
    assert aware(stored) == datetime(2026, 11, 1, 14, 59, tzinfo=UTC)


async def test_battle_window_with_offset_round_trips(api, session_factory):
    book = await make_book(session_factory, [["가" * 15]])
    users, a, b = await two_teams(api)
    starts = datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0)
    r = await users["서연"].post(
        "/api/v1/battles",
        json={
            "type": "page_race",
            "book_id": book,
            "team_a_id": a["id"],
            "team_b_id": b["id"],
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(days=1)).isoformat(),
        },
    )
    async with session_factory() as s:
        stored = (await s.get(Battle, r.json()["id"])).starts_at
    assert aware(stored) == starts.astimezone(UTC)


# ── 그 밖 ──────────────────────────────────────────────


async def test_oauth_account_with_deleted_user_is_recreated(session_factory):
    async with session_factory() as s:
        s.add(OAuthAccount(user_id=999, provider="kakao", provider_user_id="k1"))
        await s.commit()
        user = await auth_service.oauth_user(s, "kakao", "k1", "다시온사람", None)
        assert user.nickname == "다시온사람"
        assert await s.scalar(select(func.count()).select_from(OAuthAccount)) == 1


async def test_team_service_open_battle_flag(api, session_factory):
    book = await make_book(session_factory, [["가" * 15]])
    users, a, b = await two_teams(api)
    async with session_factory() as s:
        assert not await team_service.has_open_battle(s, a["id"])
    await users["서연"].post(
        "/api/v1/battles",
        json={"type": "page_race", "book_id": book, "team_a_id": a["id"], "team_b_id": b["id"], **period()},
    )
    async with session_factory() as s:
        assert await team_service.has_open_battle(s, a["id"])
