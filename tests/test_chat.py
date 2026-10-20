"""읽기방 채팅 (docs/plans/2026-10-20-native-app-design.md '읽기방 채팅')."""

from app.realtime.broker import broker, room_channel
from tests.conftest import make_book, signup, token_signup


async def setup(api, session_factory):
    book = await make_book(session_factory, [["가" * 30]])
    owner_c, guest_c, outsider_c = api(), api(), api()
    owner = await token_signup(owner_c, "방장")
    guest = await token_signup(guest_c, "손님")
    await token_signup(outsider_c, "구경꾼")
    room = (await owner_c.post("/api/v1/rooms", json={"book_id": book, "name": "수다방"})).json()
    await guest_c.post(f"/api/v1/invites/{room['invite_code']}/join")
    return room, (owner_c, owner), (guest_c, guest), outsider_c


async def test_post_and_list_messages_in_order(api, session_factory):
    room, (owner_c, owner), (guest_c, guest), _ = await setup(api, session_factory)
    url = f"/api/v1/rooms/{room['id']}/messages"
    queue, _ = broker.subscribe(room_channel(room["id"]), None)

    r = await owner_c.post(url, json={"body": "  안녕하세요!  "})
    assert r.status_code == 201, r.text
    first = r.json()
    assert set(first) == {"id", "user", "body", "created_at"}
    assert first["body"] == "안녕하세요!" and first["user"] == {
        "id": owner["id"],
        "nickname": "방장",
        "avatar_color": owner["avatar_color"],
    }
    # 커밋된 뒤 방 채널로 본문까지 실어 보낸다
    event = queue.get_nowait()
    assert event.type == "message.created"
    assert event.data["id"] == first["id"] and event.data["body"] == "안녕하세요!"
    assert event.data["user"]["avatar_color"] == owner["avatar_color"]

    for i in range(4):
        await guest_c.post(url, json={"body": f"메시지 {i}"})
    msgs = (await guest_c.get(url)).json()
    assert [m["body"] for m in msgs] == [
        "안녕하세요!",
        "메시지 0",
        "메시지 1",
        "메시지 2",
        "메시지 3",
    ]  # 오래된 → 새

    # 페이지: before보다 앞선 limit개, 역시 오래된 → 새
    page = (await guest_c.get(url, params={"before": msgs[-1]["id"], "limit": 2})).json()
    assert [m["body"] for m in page] == ["메시지 1", "메시지 2"]
    assert (await guest_c.get(url, params={"limit": 101})).status_code == 422


async def test_body_length_and_membership(api, session_factory):
    room, (owner_c, _), (guest_c, _), outsider_c = await setup(api, session_factory)
    url = f"/api/v1/rooms/{room['id']}/messages"
    for body in ("", "   ", "가" * 501):
        r = await owner_c.post(url, json={"body": body})
        assert r.status_code in (400, 422), body
    r = await owner_c.post(url, json={"body": "   "})
    assert r.json()["detail"] == "메시지는 1~500자로 써 주세요."
    assert (await owner_c.post(url, json={"body": "가" * 500})).status_code == 201

    # 멤버가 아니면 읽기도 쓰기도 못 하고, 방이 있는지도 모른다
    assert (await outsider_c.get(url)).status_code == 404
    assert (await outsider_c.post(url, json={"body": "끼워 줘"})).status_code == 404
    assert (await owner_c.get("/api/v1/rooms/9999/messages")).status_code == 404

    # 방을 나가면 더 이상 못 읽는다
    assert (await guest_c.post(f"/api/v1/rooms/{room['id']}/leave")).status_code == 204
    assert (await guest_c.get(url)).status_code == 404


async def test_cookie_session_chat_still_needs_csrf(api, session_factory):
    book = await make_book(session_factory, [["가" * 30]])
    async with api() as c:
        await signup(c, "웹사용자")
        room = (await c.post("/api/v1/rooms", json={"book_id": book, "name": "웹방"})).json()
        url = f"/api/v1/rooms/{room['id']}/messages"
        assert (await c.post(url, json={"body": "웹에서"})).status_code == 201
        del c.headers["X-CSRF-Token"]
        assert (await c.post(url, json={"body": "토큰 없이"})).status_code == 403
