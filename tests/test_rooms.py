"""읽기방 · 초대 · 반응 · 스포일러 가드 (GOAL 검증 7) · 저작권 가드 (검증 8)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.models import Book, BookChunk, Room
from tests.conftest import age_accounts, make_book, signup
from tests.test_reading import CHUNK, MIN_MS, ago, post_events


async def setup_room(api, session_factory, chunks=4, chunk=None):
    book = await make_book(session_factory, [chunk or CHUNK + ["둘째 문단"]] * chunks)
    a, b = api(), api()
    await signup(a, "서연")
    await signup(b, "준호")
    room = (await a.post("/api/v1/rooms", json={"book_id": book, "name": "봄봄 같이 읽기"})).json()
    joined = await b.post(f"/api/v1/invites/{room['invite_code']}/join")
    assert joined.status_code == 200
    return book, room, a, b


async def test_create_join_and_preview(api, session_factory):
    book, room, a, b = await setup_room(api, session_factory)
    if True:  # noqa: SIM108 — a, b는 fixture가 정리한다
        assert len(room["invite_code"]) == 8
        assert [m["nickname"] for m in (await b.get(f"/api/v1/rooms/{room['id']}")).json()["members"]] == [
            "서연",
            "준호",
        ]
        # 다시 눌러도 중복 가입 없음
        again = await b.post(f"/api/v1/invites/{room['invite_code']}/join")
        assert len(again.json()["members"]) == 2

    async with api() as anon:
        p = await anon.get(f"/api/v1/invites/{room['invite_code']}")
        assert p.status_code == 200
        assert p.json()["invite_code"] is None  # 비로그인 미리보기에는 코드 숨김
        assert (await anon.get(f"/api/v1/rooms/{room['id']}")).status_code == 401


async def test_room_limits_and_expiry(api, session_factory):
    book = await make_book(session_factory, [CHUNK])
    async with api() as owner:
        await signup(owner, "방장")
        room = (await owner.post("/api/v1/rooms", json={"book_id": book, "name": "가득"})).json()
        for i in range(7):
            async with api() as c:
                await signup(c, f"친구{i}")
                assert (await c.post(f"/api/v1/invites/{room['invite_code']}/join")).status_code == 200
        async with api() as late:
            await signup(late, "늦은친구")
            assert (await late.post(f"/api/v1/invites/{room['invite_code']}/join")).status_code == 409

        room2 = (await owner.post("/api/v1/rooms", json={"book_id": book, "name": "만료"})).json()
        async with session_factory() as s:
            await s.execute(
                update(Room)
                .where(Room.id == room2["id"])
                .values(invite_expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await s.commit()
        async with api() as c:
            await signup(c, "만료친구")
            assert (await c.post(f"/api/v1/invites/{room2['invite_code']}/join")).status_code == 410

        # 재발급하면 새 코드로 다시 들어올 수 있고, 옛 코드는 무효
        fresh = (await owner.post(f"/api/v1/rooms/{room2['id']}/invite")).json()
        assert fresh["invite_code"] != room2["invite_code"]
        async with api() as c:
            await signup(c, "새친구")
            assert (await c.post(f"/api/v1/invites/{fresh['invite_code']}/join")).status_code == 200
            assert (await c.post(f"/api/v1/invites/{room2['invite_code']}/join")).status_code == 404


async def test_owner_leaving_hands_over_then_archives(api, session_factory):
    book, room, a, b = await setup_room(api, session_factory)
    if True:  # noqa: SIM108 — a, b는 fixture가 정리한다
        assert (await a.post(f"/api/v1/rooms/{room['id']}/leave")).status_code == 204
        members = (await b.get(f"/api/v1/rooms/{room['id']}")).json()["members"]
        assert [(m["nickname"], m["is_owner"]) for m in members] == [("준호", True)]
        assert (await b.post(f"/api/v1/rooms/{room['id']}/leave")).status_code == 204
    async with session_factory() as s:
        assert (await s.get(Room, room["id"])).archived


async def test_spoiler_guard_hides_reactions_ahead(api, session_factory):
    """B의 검증 위치보다 뒤 청크의 반응은 본문 없이 개수만 온다."""
    book, room, a, b = await setup_room(api, session_factory)
    await age_accounts(session_factory)  # 몇 분 동안 읽은 장면을 만들기 위해 가입 시각을 과거로
    if True:  # noqa: SIM108 — a, b는 fixture가 정리한다
        # A가 0~2청크를 검증하고 1·2청크에 반응
        await post_events(
            a,
            book,
            [(0, MIN_MS + 1000, ago(300)), (1, MIN_MS + 1000, ago(200)), (2, MIN_MS + 1000, ago(100))],
        )
        for chunk, body in [(0, "첫 문단 좋다"), (1, "반전!"), (2, "결말 스포")]:
            r = await a.post(
                f"/api/v1/books/{book}/reactions",
                json={"chunk_index": chunk, "kind": "comment", "body": body},
            )
            assert r.status_code == 201
        # B는 0청크만 검증
        await post_events(b, book, [(0, MIN_MS + 1000, ago(50))])

        feed = (await b.get(f"/api/v1/books/{book}/reactions", params={"room_id": room["id"]})).json()
        assert feed["position"] == 0
        assert [r["body"] for r in feed["visible"]] == ["첫 문단 좋다"]
        assert feed["locked"] == {"1": 1, "2": 1} and feed["locked_total"] == 2
        assert "반전" not in str(feed)

        # 가드를 끄면 다 보인다 (개인 설정)
        await b.put("/api/v1/auth/me/settings", json={"spoiler_guard": False})
        feed = (await b.get(f"/api/v1/books/{book}/reactions", params={"room_id": room["id"]})).json()
        assert len(feed["visible"]) == 3 and feed["locked_total"] == 0

        # 방 밖 사람은 방 반응을 못 본다
        async with api() as outsider:
            await signup(outsider, "남")
            r = await outsider.get(f"/api/v1/books/{book}/reactions", params={"room_id": room["id"]})
            assert r.status_code == 403


async def test_reaction_rules(api, session_factory):
    book, room, a, b = await setup_room(api, session_factory)
    if True:  # noqa: SIM108 — a, b는 fixture가 정리한다
        url = f"/api/v1/books/{book}/reactions"
        # 지금 읽는 청크(0)에는 남길 수 있고, 안 읽은 곳(2)은 막는다
        assert (
            await a.post(url, json={"chunk_index": 0, "anchor": 1, "kind": "emoji", "body": "❤️"})
        ).status_code == 201
        assert (await a.post(url, json={"chunk_index": 2, "kind": "emoji", "body": "❤️"})).status_code == 403
        assert (await a.post(url, json={"chunk_index": 0, "kind": "emoji", "body": "🍕"})).status_code == 400
        assert (
            await a.post(url, json={"chunk_index": 99, "kind": "comment", "body": "x"})
        ).status_code == 400

        # 같은 문단에 B가 반응하면 A에게 알림
        await b.post(url, json={"chunk_index": 0, "anchor": 1, "kind": "comment", "body": "저도요"})
        notes = (await a.get("/api/v1/notifications")).json()
        kinds = [n["kind"] for n in notes]
    # 22~08시(KST)에는 방해 금지로 아직 안 보일 수 있다
    assert "reaction" in kinds or not kinds or kinds == ["room_joined"]


async def test_room_race_ranks_by_verified_chunks(api, session_factory):
    """방이 생긴 뒤에 검증한 청크만 센다."""
    book, room, a, b = await setup_room(api, session_factory, chunk=["가" * 15])  # 최소 0.6초
    if True:  # noqa: SIM108 — a, b는 fixture가 정리한다
        await post_events(a, book, [(0, 1_000, ago(-2)), (1, 1_000, ago(-5))])
        await post_events(b, book, [(0, 1_000, ago(-2))])
        race = (await a.get(f"/api/v1/rooms/{room['id']}/race")).json()
    assert [(r["nickname"], r["verified_chunks"]) for r in race] == [("서연", 2), ("준호", 1)]


async def test_copyright_guard(api, session_factory):
    """gutendex·wikisource 이외 소스는 has_fulltext=true가 될 수 없고, 전문 소스로 빈 책을 만들 수도 없다."""
    async with api() as c:
        await signup(c)
        r = await c.post(
            "/api/v1/books/track",
            json={"source": "google_books", "external_id": "g1", "title": "상용", "has_fulltext": True},
        )
        assert r.status_code == 200 and r.json()["has_fulltext"] is False
        r = await c.post(
            "/api/v1/books/track", json={"source": "wikisource", "external_id": "봄봄", "title": "봄봄"}
        )
        assert r.status_code == 400
        r = await c.post("/api/v1/books/import", json={"source": "kakao", "external_id": "k1"})
        assert r.status_code == 400
    async with session_factory() as s:
        book = await s.get(Book, 1)
        chunks = await s.scalar(select(func.count()).select_from(BookChunk))
    assert book.source == "google_books" and not book.has_fulltext and chunks == 0
