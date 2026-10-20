"""체류시간 검증 (GOAL 검증 6) · 서재 · 트래커 모드 · 포인트 적립."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import PointsLog, ReadingEvent
from tests.conftest import age_accounts, make_book, signup

# 공백 없는 한글 1,500자 = 최소 체류시간 60초 (상한 1,500자/분)
CHUNK = ["가" * 1500]
MIN_MS = 60_000


def ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


async def post_events(c, book_id, events):
    r = await c.post(
        f"/api/v1/books/{book_id}/events",
        json={"events": [{"chunk_index": i, "dwell_ms": d, "occurred_at": at} for i, d, at in events]},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_chunk_below_min_dwell_is_not_counted(api, session_factory):
    book = await make_book(session_factory, [CHUNK] * 4)
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await post_events(c, book, [(0, MIN_MS - 1, ago(1))])
        assert r["newly_verified"] == [] and r["progress_pct"] == 0 and r["points_awarded"] == 0

        # 재방문하면 누적으로 인정된다
        r = await post_events(c, book, [(0, 5_000, ago(0))])
        assert r["newly_verified"] == [0]
        assert r["verified_chunk"] == 0 and r["progress_pct"] == 25 and r["points_awarded"] == 1

        # 같은 청크는 다시 검증되지 않는다 (레이스 점수 중복 방지)
        r = await post_events(c, book, [(0, MIN_MS, ago(-0.5))])
        assert r["newly_verified"] == []


async def test_server_caps_dwell_by_timestamp_gap(api, session_factory):
    """클라이언트가 60초라고 주장해도 직전 이벤트와 5초 간격이면 5초만 인정한다."""
    book = await make_book(session_factory, [CHUNK] * 3)
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await post_events(c, book, [(0, MIN_MS + 1_000, ago(100)), (1, MIN_MS + 1_000, ago(95))])
        assert r["newly_verified"] == [0]
    async with session_factory() as s:
        rows = list(await s.scalars(select(ReadingEvent).order_by(ReadingEvent.id)))
    assert [(e.chunk_index, e.dwell_ms, e.verified) for e in rows] == [
        (0, MIN_MS + 1_000, True),
        (1, 5_000, False),
    ]


async def test_idle_tab_is_capped_and_future_events_dropped(api, session_factory):
    book = await make_book(session_factory, [["가" * 150]] * 2)  # 최소 6초
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await post_events(c, book, [(0, 3_600_000, ago(4000)), (1, 1000, ago(-3600))])
        assert r["accepted"] == 1  # 1시간 뒤 시각의 이벤트는 버린다
    async with session_factory() as s:
        e = await s.scalar(select(ReadingEvent))
    assert e.dwell_ms == 60_000  # 최소 체류시간 × 10 상한


async def test_late_offline_events_count_for_progress_not_race(api, session_factory):
    book = await make_book(session_factory, [CHUNK] * 2)
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await post_events(c, book, [(0, MIN_MS, ago(25 * 3600))])
        assert r["progress_pct"] == 50
    async with session_factory() as s:
        e = await s.scalar(select(ReadingEvent))
    assert e.verified and not e.race_eligible


async def test_slow_down_hint_after_skimming(api, session_factory):
    book = await make_book(session_factory, [CHUNK] * 8)
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await post_events(c, book, [(i, 2_000, ago(20 - i * 2)) for i in range(6)])
        assert r["slow_down"] is True and r["newly_verified"] == []


async def test_finish_book_suggests_done_then_awards_once(api, session_factory):
    book = await make_book(session_factory, [CHUNK] * 2)
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await post_events(c, book, [(0, MIN_MS, ago(200)), (1, MIN_MS, ago(100))])
        assert r["progress_pct"] == 100 and r["suggest_done"] is True
        for _ in range(2):
            e = await c.put(f"/api/v1/library/{book}", json={"shelf": "done"})
            assert e.json()["shelf"] == "done"
        pts = (await c.get("/api/v1/points")).json()
    sources = sorted(h["source"] for h in pts["history"])
    assert sources.count("complete") == 1
    assert pts["balance"] == 2 + 50


async def test_chunk_points_daily_cap(api, session_factory):
    book = await make_book(session_factory, [["가" * 15]] * 120)  # 최소 0.6초
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await post_events(c, book, [(i, 1_000, ago(500 - i * 2)) for i in range(120)])
        assert len(r["newly_verified"]) == 120
        assert r["points_awarded"] == 100
    async with session_factory() as s:
        chunk_pts = sum(
            p.amount for p in await s.scalars(select(PointsLog).where(PointsLog.source == "chunk"))
        )
    assert chunk_pts == 100


async def test_tracker_mode(api, session_factory):
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await c.post(
            "/api/v1/books/track",
            json={"source": "kakao", "external_id": "978893", "title": "상용 소설", "authors": ["작가"]},
        )
        assert r.status_code == 200
        book = r.json()
        assert book["has_fulltext"] is False and book["shelf"] == "want"

        p = await c.put(
            f"/api/v1/library/{book['book_id']}/progress", json={"current_page": 50, "total_pages": 200}
        )
        assert p.json()["progress_pct"] == 25 and p.json()["shelf"] == "reading"

        # 트래커 도서는 리더 이벤트를 받지 않는다
        ev = await c.post(f"/api/v1/books/{book['book_id']}/events", json={"events": []})
        assert ev.status_code == 400


async def test_fulltext_book_rejects_manual_progress(api, session_factory):
    book = await make_book(session_factory, [CHUNK])
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        r = await c.put(f"/api/v1/library/{book}/progress", json={"progress_pct": 90})
    assert r.status_code == 400


async def test_library_lists_entries(api, session_factory):
    book = await make_book(session_factory, [CHUNK])
    async with api() as c:
        await signup(c)
        await age_accounts(session_factory)
        await c.put(f"/api/v1/library/{book}", json={"shelf": "want"})
        lib = (await c.get("/api/v1/library")).json()
    assert [(e["book_id"], e["shelf"]) for e in lib] == [(book, "want")]
