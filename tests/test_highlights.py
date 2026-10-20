"""개인 밑줄 · 메모 (docs/plans/2026-10-20-native-app-design.md '밑줄 · 메모')."""

from tests.conftest import make_book, set_position, token_signup

PARAS = [
    ["봄이 오면   산에 들에\n진달래 피네.", "둘째 문단이에요."],
    ["여름에는 소나기가 와요."],
    ["가을에는 낙엽이 져요."],
    ["겨울에는 눈이 와요."],
]


async def post(c, book, **kw):
    body = {"chunk_index": 0, "anchor": 0, "quote": "진달래 피네", "color": "yellow", "visibility": "private"}
    return await c.post(f"/api/v1/books/{book}/highlights", json={**body, **kw})


async def test_create_validates_quote_and_position(api, session_factory):
    book = await make_book(session_factory, PARAS)
    async with api() as c:
        me = await token_signup(c, "밑줄")
        # 공백·줄바꿈이 달라도 본문에 있으면 된다
        r = await post(c, book, quote="봄이 오면 산에\n들에 진달래", note="  좋은 문장  ", color="green")
        assert r.status_code == 201, r.text
        h = r.json()
        assert set(h) == {
            "id",
            "book_id",
            "chunk_index",
            "anchor",
            "quote",
            "note",
            "color",
            "visibility",
            "created_at",
            "user",
        }
        assert (
            h["quote"] == "봄이 오면 산에 들에 진달래" and h["note"] == "좋은 문장" and h["color"] == "green"
        )
        assert h["user"]["id"] == me["id"]

        r = await post(c, book, quote="본문에 없는 문장")
        assert r.status_code == 400 and r.json()["detail"] == "밑줄 문장이 본문에 없어요."
        # 읽은 위치(-1) + 1 = 0청크까지만
        r = await post(c, book, chunk_index=1, quote="소나기")
        assert r.status_code == 403
        await set_position(session_factory, me["id"], book, 0)
        assert (await post(c, book, chunk_index=1, quote="소나기")).status_code == 201
        assert (await post(c, book, chunk_index=2, quote="낙엽")).status_code == 403
        assert (await post(c, book, chunk_index=9, quote="눈")).status_code == 400
        assert (await post(c, book, color="purple")).status_code == 422
        assert (await post(c, book, visibility="public")).status_code == 422
        assert (await post(c, book, quote="   ")).status_code == 400
        assert (await post(c, book, note="가" * 281)).status_code == 400
        assert (
            await c.post("/api/v1/books/9999/highlights", json={"chunk_index": 0, "quote": "x"})
        ).status_code == 404

        tracked = await c.post(
            "/api/v1/books/track", json={"source": "manual", "external_id": "t", "title": "종이책"}
        )
        r = await post(c, tracked.json()["book_id"], quote="아무거나")
        assert r.status_code == 400 and "앱 안에서 읽는 책" in r.json()["detail"]


async def test_my_highlights_patch_delete_and_ownership(api, session_factory):
    book = await make_book(session_factory, PARAS)
    other_book = await make_book(session_factory, PARAS, title="다른 책")
    async with api() as c, api() as other:
        await token_signup(c, "주인")
        await token_signup(other, "남")
        a = (await post(c, book)).json()
        b = (await post(c, other_book, quote="둘째 문단")).json()

        mine = (await c.get("/api/v1/me/highlights")).json()
        assert [h["id"] for h in mine] == [b["id"], a["id"]]
        assert mine[0]["book"]["id"] == other_book and {"cover_color", "readers"} <= set(mine[0]["book"])
        only = (await c.get("/api/v1/me/highlights", params={"book_id": book})).json()
        assert [h["id"] for h in only] == [a["id"]]

        r = await c.patch(f"/api/v1/highlights/{a['id']}", json={"note": "메모 추가", "color": "pink"})
        assert r.status_code == 200 and (r.json()["note"], r.json()["color"]) == ("메모 추가", "pink")
        r = await c.patch(f"/api/v1/highlights/{a['id']}", json={"color": None})
        assert r.json()["color"] == "pink" and r.json()["note"] == "메모 추가"  # 보낸 null 색은 무시
        r = await c.patch(f"/api/v1/highlights/{a['id']}", json={"note": None})
        assert r.json()["note"] is None
        assert (await c.patch(f"/api/v1/highlights/{a['id']}", json={"color": "red"})).status_code == 422

        # 남의 밑줄은 고치지도 지우지도 못하고, 있는지도 모른다
        assert (await other.patch(f"/api/v1/highlights/{a['id']}", json={"note": "x"})).status_code == 404
        assert (await other.delete(f"/api/v1/highlights/{a['id']}")).status_code == 404
        assert (await other.get("/api/v1/me/highlights")).json() == []

        assert (await c.delete(f"/api/v1/highlights/{a['id']}")).status_code == 204
        assert (await c.delete(f"/api/v1/highlights/{a['id']}")).status_code == 404
        assert [h["id"] for h in (await c.get("/api/v1/me/highlights")).json()] == [b["id"]]


async def test_friends_highlights_spoiler_guard_and_privacy(api, session_factory):
    book = await make_book(session_factory, PARAS)
    async with api() as author_c, api() as reader_c, api() as stranger_c:
        author = await token_signup(author_c, "작가")
        reader = await token_signup(reader_c, "독자")
        await token_signup(stranger_c, "남")
        await set_position(session_factory, author["id"], book, 3)
        await set_position(session_factory, reader["id"], book, 1)
        await post(author_c, book, chunk_index=0, quote="진달래", visibility="friends")
        await post(author_c, book, chunk_index=1, quote="소나기", visibility="friends")
        await post(author_c, book, chunk_index=1, quote="여름에는", visibility="private")
        await post(author_c, book, chunk_index=2, quote="낙엽", visibility="friends")
        await post(author_c, book, chunk_index=3, quote="눈이", visibility="friends")
        # 배틀 밑줄이 아닌 개인 밑줄만, 내 밑줄은 friends 목록에 안 섞인다
        await post(reader_c, book, chunk_index=0, quote="둘째", visibility="friends")

        url = f"/api/v1/books/{book}/highlights"
        # 팔로우하지 않으면 아무것도 안 보인다
        assert (await reader_c.get(url, params={"scope": "friends"})).json() == {
            "position": 1,
            "visible": [],
            "locked_total": 0,
        }
        await reader_c.post(f"/api/v1/users/{author['id']}/follow")
        r = (await reader_c.get(url, params={"scope": "friends"})).json()
        assert [h["quote"] for h in r["visible"]] == ["진달래", "소나기"]  # 비공개 밑줄은 절대 안 보인다
        assert r["locked_total"] == 2 and r["position"] == 1
        assert "낙엽" not in str(r) and "여름에는" not in str(r)

        await reader_c.put("/api/v1/auth/me/profile", json={"spoiler_guard": False})
        r = (await reader_c.get(url)).json()
        assert [h["quote"] for h in r["visible"]] == ["진달래", "소나기", "낙엽", "눈이"] and r[
            "locked_total"
        ] == 0

        # 팔로우는 한쪽 방향: 작가는 독자를 팔로우하지 않았으므로 독자의 밑줄이 안 보인다
        assert (await author_c.get(url)).json()["visible"] == []
        # scope=mine은 내 밑줄 전부(비공개 포함)
        mine = (await author_c.get(url, params={"scope": "mine"})).json()["visible"]
        assert [h["quote"] for h in mine] == ["진달래", "소나기", "여름에는", "낙엽", "눈이"]
        assert (await author_c.get(url, params={"scope": "everyone"})).status_code == 422
