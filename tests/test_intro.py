from tests.test_api import upstream


async def test_intro_is_public(api):
    async with api(upstream) as c:
        r = await c.get("/intro")
    assert r.status_code == 200
    for text in [
        "偕讀",
        "함께 해",
        "읽을 독",
        "같은 책을, 각자의 속도로, 함께 읽어요.",
        "이렇게 읽어요",
        "세 가지 약속",
        "/static/intro/5-reader.jpg",
    ]:
        assert text in r.text
