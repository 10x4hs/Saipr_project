"""읽기 통계 · 배지 (docs/plans/2026-10-20-native-app-design.md '통계 · 배지')."""

from datetime import UTC, date, datetime, time, timedelta

from app import models
from app.core.clock import KST, kst_date
from app.services.stats import best_run
from tests.conftest import make_book, token_signup


async def add_events(session_factory, user_id: int, book_id: int, rows) -> None:
    """(KST 날짜, 시, 체류 ms, verified, chunk) — 인정된 체류시간을 바로 넣는다."""
    async with session_factory() as s:
        for d, hour, ms, verified, chunk in rows:
            at = datetime.combine(d, time(hour), KST).astimezone(UTC)
            s.add(
                models.ReadingEvent(
                    user_id=user_id,
                    book_id=book_id,
                    chunk_index=chunk,
                    dwell_ms=ms,
                    verified=verified,
                    occurred_at=at,
                    received_at=at,
                )
            )
        await s.commit()


def test_best_run():
    d = date(2026, 1, 1)
    assert best_run(set()) == 0
    assert best_run({d, d + timedelta(1), d + timedelta(3), d + timedelta(4), d + timedelta(5)}) == 3


async def test_stats_minutes_week_heatmap_and_streaks(api, session_factory):
    book = await make_book(session_factory, [["가" * 30]] * 40)
    today = kst_date(datetime.now(UTC))
    async with api() as c:
        me = await token_signup(c, "통계")
        rows = [
            (today, 9, 90_000, True, 0),  # 오늘 1.5분 → 1분
            (today, 9, 30_000, False, 1),  # 오늘 0.5분 (미검증도 체류시간은 센다)
            (today - timedelta(1), 9, 120_000, True, 1),
            (today - timedelta(2), 9, 60_000, True, 2),
            # 30일 전 5일 연속 → 최고 기록 5일
            *[(today - timedelta(30 + i), 9, 60_000, True, 3 + i) for i in range(5)],
            (today - timedelta(100), 9, 600_000, True, 20),  # 히트맵(84일) 밖
        ]
        await add_events(session_factory, me["id"], book, rows)
        await c.put("/api/v1/auth/me/profile", json={"daily_goal_minutes": 30, "yearly_goal_books": 5})

        r = await c.get("/api/v1/me/stats")
        assert r.status_code == 200, r.text
        s = r.json()
        assert set(s) == {
            "today_minutes",
            "week",
            "heatmap",
            "streak",
            "best_streak",
            "books_done",
            "books_done_year",
            "yearly_goal_books",
            "daily_goal_minutes",
            "total_minutes",
            "total_chunks",
            "reactions",
            "highlights",
        }
        assert s["today_minutes"] == 2  # 90초 + 30초
        assert len(s["week"]) == 7 and s["week"][-1] == {"date": today.isoformat(), "minutes": 2, "chunks": 1}
        assert s["week"][-2] == {"date": (today - timedelta(1)).isoformat(), "minutes": 2, "chunks": 1}
        assert len(s["heatmap"]) == 84 and s["heatmap"][0]["date"] == (today - timedelta(83)).isoformat()
        assert sum(h["minutes"] for h in s["heatmap"]) == 2 + 2 + 1 + 5
        assert s["streak"] == 3 and s["best_streak"] == 5
        assert s["total_minutes"] == (90 + 30 + 120 + 60 + 300 + 600) // 60
        assert s["total_chunks"] == 9
        assert (s["daily_goal_minutes"], s["yearly_goal_books"]) == (30, 5)
        assert (s["books_done"], s["books_done_year"], s["reactions"], s["highlights"]) == (0, 0, 0, 0)


async def test_kst_day_boundary(api, session_factory):
    """KST 자정 직전과 직후는 다른 날이다(UTC로는 같은 날이어도)."""
    book = await make_book(session_factory, [["가" * 30]] * 3)
    today = kst_date(datetime.now(UTC))
    async with api() as c:
        me = await token_signup(c, "자정")
        y = today - timedelta(1)
        await add_events(
            session_factory, me["id"], book, [(y, 23, 60_000, True, 0), (today, 0, 120_000, True, 1)]
        )
        week = (await c.get("/api/v1/me/stats")).json()["week"]
        assert [w["minutes"] for w in week[-2:]] == [1, 2]


async def test_badges_progress_and_earned_once(api, session_factory):
    book = await make_book(session_factory, [["가" * 30]] * 5)
    today = kst_date(datetime.now(UTC))
    async with api() as c, api() as f1, api() as f2:
        me = await token_signup(c, "배지")
        others = [await token_signup(x, f"친구{i}") for i, x in enumerate((f1, f2))]
        await add_events(
            session_factory,
            me["id"],
            book,
            [(today - timedelta(2 - i), 23 if i == 0 else 10, 60_000, True, i) for i in range(3)],
        )
        for o in others:
            await c.post(f"/api/v1/users/{o['id']}/follow")

        r = await c.get("/api/v1/me/badges")
        assert r.status_code == 200
        badges = {b["code"]: b for b in r.json()}
        assert list(badges) == [
            "first_page",
            "first_finish",
            "streak_3",
            "streak_7",
            "streak_30",
            "reactions_10",
            "highlights_10",
            "friends_3",
            "race_win",
            "night_reader",
        ]
        assert set(badges["first_page"]) == {
            "code",
            "title",
            "description",
            "icon",
            "earned",
            "earned_at",
            "progress",
            "goal",
        }
        assert badges["first_page"]["earned"] and badges["first_page"]["earned_at"]
        assert badges["streak_3"]["earned"] and badges["night_reader"]["earned"]
        assert badges["streak_7"] == {**badges["streak_7"], "earned": False, "earned_at": None, "progress": 3}
        assert badges["friends_3"]["progress"] == 2 and not badges["friends_3"]["earned"]
        assert badges["first_finish"]["progress"] == 0

        # 다시 봐도 배지 활동은 한 번만, 피드에 뜬다
        again = {b["code"]: b for b in (await c.get("/api/v1/me/badges")).json()}
        assert again["first_page"]["earned_at"] == badges["first_page"]["earned_at"]
        feed = (await c.get("/api/v1/feed")).json()
        titles = sorted(a["data"]["title"] for a in feed if a["kind"] == "badge")
        assert titles == sorted(["첫 쪽", "3일 연속", "밤 독서"])
