"""친구 찾기 · 팔로우 · 응원 · 프로필 (docs/plans/2026-10-20-native-app-design.md '친구 · 피드')."""

import pytest
from sqlalchemy import select

from app.models import Notification
from tests.conftest import make_book, set_position, token_signup

MINI = {"id", "nickname", "avatar_color"}


async def test_search_by_nickname_or_friend_code(api):
    async with api() as a, api() as b, api() as c:
        me = await token_signup(a, "책벌레서연")
        junho = await token_signup(b, "준호")
        await token_signup(c, "준호팬")

        r = await a.get("/api/v1/users/search", params={"q": "준호"})
        assert r.status_code == 200
        rows = r.json()
        assert [u["nickname"] for u in rows] == ["준호", "준호팬"]  # 짧은 이름(정확도 높은 쪽)부터
        assert set(rows[0]) == MINI | {"is_following"} and rows[0]["is_following"] is False

        r = await a.get("/api/v1/users/search", params={"q": junho["friend_code"].lower()})
        assert [u["id"] for u in r.json()] == [junho["id"]]

        # 나 자신은 나오지 않는다 · LIKE 와일드카드는 글자 그대로
        assert (await a.get("/api/v1/users/search", params={"q": me["friend_code"]})).json() == []
        assert (await a.get("/api/v1/users/search", params={"q": "%"})).json() == []
        assert (await a.get("/api/v1/users/search", params={"q": ""})).status_code == 422


async def test_follow_unfollow_and_lists(api, session_factory):
    async with api() as a, api() as b:
        me = await token_signup(a, "서연")
        other = await token_signup(b, "준호")

        r = await a.post(f"/api/v1/users/{me['id']}/follow")
        assert r.status_code == 400 and r.json()["detail"] == "나 자신은 팔로우할 수 없어요."
        assert (await a.post("/api/v1/users/9999/follow")).status_code == 404

        for _ in range(2):  # 두 번 눌러도 한 번
            assert (await a.post(f"/api/v1/users/{other['id']}/follow")).status_code == 204
        assert [u["id"] for u in (await a.get("/api/v1/me/following")).json()] == [other["id"]]
        followers = (await b.get("/api/v1/me/followers")).json()
        assert followers == [{"id": me["id"], "nickname": "서연", "avatar_color": me["avatar_color"]}]
        assert (await b.get("/api/v1/me/following")).json() == []

        r = await a.get("/api/v1/users/search", params={"q": "준호"})
        assert r.json()[0]["is_following"] is True

        assert (await a.delete(f"/api/v1/users/{other['id']}/follow")).status_code == 204
        assert (await a.get("/api/v1/me/following")).json() == []
        assert (await a.delete(f"/api/v1/users/{other['id']}/follow")).status_code == 204

    async with session_factory() as s:
        kinds = list(await s.scalars(select(Notification.kind).where(Notification.user_id == other["id"])))
    assert kinds == ["follow"]  # 두 번 눌러도 알림은 한 번


async def test_cheer_once_a_day(api, session_factory):
    async with api() as a, api() as b:
        me = await token_signup(a, "응원단")
        other = await token_signup(b, "독자")
        assert (await a.post(f"/api/v1/users/{me['id']}/cheer")).status_code == 400
        assert (await a.post("/api/v1/users/9999/cheer")).status_code == 404
        r = await a.post(f"/api/v1/users/{other['id']}/cheer")
        assert r.status_code == 202 and r.json() == {"delivered": True}
        r = await a.post(f"/api/v1/users/{other['id']}/cheer")
        assert r.status_code == 409 and "오늘은 이미 응원했어요" in r.json()["detail"]
        # 상대가 나를 응원하는 건 따로 센다
        assert (await b.post(f"/api/v1/users/{me['id']}/cheer")).status_code == 202
    async with session_factory() as s:
        bodies = list(await s.scalars(select(Notification.body).where(Notification.kind == "cheer")))
    assert len(bodies) == 2 and "응원단님이 응원을 보냈어요" in bodies[0]


async def test_double_tap_race_gives_409_not_500(session_factory, monkeypatch):
    """두 요청이 동시에 '아직 안 했다'를 확인하고 들어온 상황 — 중복은 DB가 막고 409로 끝난다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Cheer, Follow, User
    from app.services import friends
    from app.services.friends import FriendError

    async with session_factory() as s:
        a, b = User(nickname="가"), User(nickname="나")
        s.add_all([a, b])
        await s.commit()
        ids = a.id, b.id
    async with session_factory() as s:
        await friends.cheer(s, await s.get(User, ids[0]), ids[1])
        await friends.follow(s, await s.get(User, ids[0]), ids[1])

    real_get = AsyncSession.get

    async def blind_get(self, model, key, *args, **kw):  # 앞선 확인이 경쟁에 져서 못 본 것처럼
        return None if model in (Cheer, Follow) else await real_get(self, model, key, *args, **kw)

    monkeypatch.setattr(AsyncSession, "get", blind_get)
    async with session_factory() as s:
        with pytest.raises(FriendError) as e:
            await friends.cheer(s, await s.get(User, ids[0]), ids[1])
        assert e.value.status == 409
    async with session_factory() as s:
        await friends.follow(s, await s.get(User, ids[0]), ids[1])  # 이미 팔로우 — 조용히 끝난다


async def test_profile_shape_and_highlight_privacy(api, session_factory):
    book = await make_book(session_factory, [["첫 문장이에요."], ["둘째 문장이에요."], ["셋째 문장이에요."]])
    async with api() as a, api() as b, api() as stranger:
        author = await token_signup(a, "작가")
        fan = await token_signup(b, "팬")
        await token_signup(stranger, "남")
        await set_position(session_factory, author["id"], book, 2)
        await set_position(session_factory, fan["id"], book, 0)
        for chunk, quote, vis in (
            (0, "첫 문장", "friends"),
            (1, "둘째 문장", "private"),
            (2, "셋째", "friends"),
        ):
            r = await a.post(
                f"/api/v1/books/{book}/highlights",
                json={"chunk_index": chunk, "anchor": 0, "quote": quote, "visibility": vis, "note": "메모"},
            )
            assert r.status_code == 201, r.text
        await b.put("/api/v1/auth/me/profile", json={"bio": "읽는 중"})
        await b.post(f"/api/v1/users/{author['id']}/follow")

        p = (await b.get(f"/api/v1/users/{author['id']}")).json()
        assert set(p) == MINI | {
            "bio",
            "is_following",
            "followers",
            "following",
            "stats",
            "reading",
            "highlights",
        }
        assert p["is_following"] is True and p["followers"] == 1 and p["following"] == 0
        assert set(p["stats"]) == {"books_done", "streak", "minutes_week"}
        assert p["reading"][0]["id"] == book and p["reading"][0]["progress_pct"] == 0
        assert {"cover_color", "readers", "genre"} <= set(p["reading"][0])
        # 친구 공개만, 새 것부터. 팬은 0청크까지 읽었으므로 2청크 밑줄은 잠긴다
        hs = p["highlights"]
        assert [h["chunk_index"] for h in hs] == [2, 0]
        assert hs[0]["locked"] is True and hs[0]["quote"] is None and hs[0]["note"] is None
        assert hs[1]["quote"] == "첫 문장" and hs[1]["note"] == "메모" and hs[1]["locked"] is False

        # 팔로우하지 않은 사람에게는 밑줄이 보이지 않는다
        p = (await stranger.get(f"/api/v1/users/{author['id']}")).json()
        assert p["is_following"] is False and p["highlights"] == []
        # 나 자신은 내 친구 공개 밑줄을 모두 본다(잠금 없음)
        p = (await a.get(f"/api/v1/users/{author['id']}")).json()
        assert [h["locked"] for h in p["highlights"]] == [False, False]

        assert (await b.get("/api/v1/users/9999")).status_code == 404
        assert (await b.get(f"/api/v1/users/{fan['id']}")).json()["bio"] == "읽는 중"


async def test_social_requires_login(api):
    async with api() as c:
        for method, url in (
            ("GET", "/api/v1/users/search?q=a"),
            ("GET", "/api/v1/users/1"),
            ("GET", "/api/v1/me/following"),
            ("GET", "/api/v1/feed"),
            ("GET", "/api/v1/me/stats"),
            ("GET", "/api/v1/me/badges"),
            ("GET", "/api/v1/me/highlights"),
        ):
            assert (await c.request(method, url)).status_code == 401, url
