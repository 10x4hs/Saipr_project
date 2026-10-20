"""친구 피드 — 활동 기록 · 팔로우한 사람 + 나 · 스포일러 가드 · 페이지 (docs/plans/2026-10-20-native-app-design.md)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import Activity
from tests.conftest import age_accounts, make_book, set_position, token_signup

SHORT = ["가" * 15]  # 최소 체류시간이 짧은 청크


def at(seconds_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


async def read_chunks(c, book_id: int, indices: list[int], step: int = 0) -> dict:
    """청크를 6초 간격으로 읽은 것처럼 보낸다. step은 앞서 보낸 이벤트 수(같은 사용자의 다음 배치는 그 뒤 시각).

    서버는 지난 배치를 받은 시각보다 앞선 이벤트와, 직전 이벤트와의 간격보다 긴 체류를 인정하지 않는다.
    테스트는 실제로 기다리지 않으므로 조금 뒤 시각(허용 오차 30초 안)으로 보낸다.
    """
    events = [
        {"chunk_index": i, "dwell_ms": 5_000, "occurred_at": at(-1 - (step + n) * 6)}
        for n, i in enumerate(indices)
    ]
    r = await c.post(f"/api/v1/books/{book_id}/events", json={"events": events})
    assert r.status_code == 200, r.text
    return r.json()


async def kinds(c) -> list[tuple[str, dict]]:
    r = await c.get("/api/v1/feed")
    assert r.status_code == 200, r.text
    return [(a["kind"], a["data"]) for a in r.json()]


async def test_finishing_in_one_go_skips_milestones(api, session_factory):
    """한 번에 끝까지 읽으면 중간 이정표 대신 완독 하나만 남긴다(피드가 시끄럽지 않게)."""
    book = await make_book(session_factory, [SHORT] * 4)
    async with api() as c:
        await token_signup(c, "단숨에")
        await age_accounts(session_factory)
        await read_chunks(c, book, [0, 1, 2, 3])
        assert [k for k, _ in await kinds(c)] == ["finished", "started"]


async def test_reading_records_started_milestones_finished(api, session_factory):
    book = await make_book(session_factory, [SHORT] * 4)
    async with api() as c:
        await token_signup(c, "독자")
        await age_accounts(session_factory)
        await read_chunks(c, book, [0])
        assert await kinds(c) == [("milestone", {"pct": 25}), ("started", {})]
        for i in (1, 2, 3):
            r = await read_chunks(c, book, [i], step=i)
        assert r["progress_pct"] == 100
        feed = await kinds(c)
        assert [k for k, _ in feed] == ["finished", "milestone", "milestone", "milestone", "started"]
        assert [d.get("pct") for k, d in feed if k == "milestone"] == [75, 50, 25]
        # 완독 칸으로 옮겨도 finished는 한 번만
        assert (await c.put(f"/api/v1/library/{book}", json={"shelf": "done"})).status_code == 200
        assert [k for k, _ in await kinds(c)].count("finished") == 1

        item = (await c.get("/api/v1/feed")).json()[0]
        assert set(item) == {"id", "user", "kind", "book", "data", "created_at"}
        assert set(item["user"]) == {"id", "nickname", "avatar_color"}
        assert item["book"]["id"] == book and item["book"]["readers"] == 1


async def test_tracker_progress_and_room_join(api, session_factory):
    book = await make_book(session_factory, [SHORT])
    async with api() as a, api() as b:
        await token_signup(a, "방장")
        await token_signup(b, "손님")
        tracked = await a.post(
            "/api/v1/books/track", json={"source": "manual", "external_id": "x-1", "title": "종이책"}
        )
        tracker_id = tracked.json()["book_id"]
        await a.put(f"/api/v1/library/{tracker_id}/progress", json={"progress_pct": 60})
        await a.put(f"/api/v1/library/{tracker_id}/progress", json={"progress_pct": 55})  # 내려가면 기록 없음
        assert [(k, d.get("pct")) for k, d in await kinds(a)] == [
            ("milestone", 50),
            ("milestone", 25),
            ("started", None),
        ]

        room = (await a.post("/api/v1/rooms", json={"book_id": book, "name": "같이 읽어요"})).json()
        await b.post(f"/api/v1/invites/{room['invite_code']}/join")
        await b.post(f"/api/v1/invites/{room['invite_code']}/join")  # 다시 눌러도 한 번
        assert await kinds(b) == [("joined_room", {"room_name": "같이 읽어요"})]
        assert (await kinds(a))[0] == ("joined_room", {"room_name": "같이 읽어요"})


async def test_feed_shows_following_and_me_only_with_paging(api, session_factory):
    book = await make_book(session_factory, [SHORT] * 4)
    async with api() as me_c, api() as friend_c, api() as other_c:
        me = await token_signup(me_c, "나")
        friend = await token_signup(friend_c, "친구")
        await token_signup(other_c, "모르는사람")
        await age_accounts(session_factory)
        for c in (friend_c, other_c):
            for i in range(4):
                await read_chunks(c, book, [i], step=i)  # 각자 활동 5개
        assert await kinds(me_c) == []

        await me_c.post(f"/api/v1/users/{friend['id']}/follow")
        page1 = (await me_c.get("/api/v1/feed", params={"limit": 3})).json()
        assert len(page1) == 3 and {a["user"]["id"] for a in page1} == {friend["id"]}
        page2 = (await me_c.get("/api/v1/feed", params={"limit": 3, "before": page1[-1]["id"]})).json()
        assert len(page2) == 2 and page2[0]["id"] < page1[-1]["id"]
        assert [a["kind"] for a in page1 + page2] == [
            "finished",
            "milestone",
            "milestone",
            "milestone",
            "started",
        ]

        tracked = await me_c.post(
            "/api/v1/books/track", json={"source": "manual", "external_id": "y", "title": "내 책"}
        )
        await me_c.put(f"/api/v1/library/{tracked.json()['book_id']}/progress", json={"progress_pct": 10})
        newest = (await me_c.get("/api/v1/feed")).json()[0]
        assert newest["user"]["id"] == me["id"] and newest["kind"] == "started"
        assert (await me_c.get("/api/v1/feed", params={"limit": 0})).status_code == 422


async def test_highlight_activity_privacy_and_spoiler_guard(api, session_factory):
    book = await make_book(session_factory, [["하나 둘 셋."], ["넷 다섯 여섯."], ["일곱 여덟."]])
    async with api() as a, api() as b:
        author = await token_signup(a, "밑줄러")
        reader = await token_signup(b, "구독자")
        await b.post(f"/api/v1/users/{author['id']}/follow")
        await set_position(session_factory, author["id"], book, 2)
        await set_position(session_factory, reader["id"], book, 0)

        hl = lambda chunk, quote, vis: a.post(  # noqa: E731
            f"/api/v1/books/{book}/highlights",
            json={"chunk_index": chunk, "anchor": 0, "quote": quote, "note": "좋다", "visibility": vis},
        )
        private = (await hl(0, "하나 둘", "private")).json()
        ahead = (await hl(2, "일곱", "friends")).json()
        shown = (await hl(0, "셋", "friends")).json()

        feed = [(k, d) for k, d in await kinds(b) if k == "highlight"]
        assert len(feed) == 2  # 비공개 밑줄은 피드에 없다
        newest, older = feed[0][1], feed[1][1]
        assert newest["quote"] == "셋" and newest["note"] == "좋다" and newest["locked"] is False
        assert older["locked"] is True and older["quote"] is None and older["note"] is None  # 아직 안 읽은 곳
        assert "하나 둘" not in str((await b.get("/api/v1/feed")).json())

        # 스포일러 가드를 끄면 보인다
        await b.put("/api/v1/auth/me/profile", json={"spoiler_guard": False})
        assert [d["quote"] for k, d in await kinds(b) if k == "highlight"] == ["셋", "일곱"]

        # 메모를 고치면 피드도 바뀌고, 비공개로 돌리거나 지우면 피드에서 사라진다
        await a.patch(f"/api/v1/highlights/{shown['id']}", json={"note": "고친 메모"})
        assert [d["note"] for k, d in await kinds(b) if k == "highlight"][0] == "고친 메모"
        await a.patch(f"/api/v1/highlights/{shown['id']}", json={"visibility": "private"})
        await a.delete(f"/api/v1/highlights/{ahead['id']}")
        assert [k for k, _ in await kinds(b) if k == "highlight"] == []
        await a.patch(f"/api/v1/highlights/{private['id']}", json={"visibility": "friends"})
        assert [d["quote"] for k, d in await kinds(b) if k == "highlight"] == ["하나 둘"]

    async with session_factory() as s:
        n = await s.scalar(select(func.count()).select_from(Activity).where(Activity.kind == "highlight"))
    assert n == 1
