"""리더: 쪽 이동은 읽음이 아니고, 다시 열면 '다 읽은 쪽 + 1'에서 이어 읽는다."""

from app.services.pace import PAGE_DWELL_MS
from tests.conftest import read_chunk, signup
from tests.test_api import upstream


async def _open(c) -> tuple[str, str, dict]:
    url = (await c.get("/open/wikisource/긴글")).headers["location"]
    token = (await c.get(url)).text.split('data-csrf="')[1].split('"')[0]
    return url, url.rsplit("/", 1)[1], {"X-CSRF-Token": token}


async def test_jumped_page_is_not_read_and_resume_is_verified_plus_one(api, clock):
    async with api(upstream) as c:
        await signup(c)
        url, book_id, h = await _open(c)
        await read_chunk(c, book_id, 0, h["X-CSRF-Token"], clock)
        # 마지막 쪽으로 건너뛰어 오래 머물러도 읽음이 아니다
        await c.put(f"/api/v1/books/{book_id}/progress", json={"chunk_index": 2}, headers=h)
        clock(10)
        jumped = await c.put(
            f"/api/v1/books/{book_id}/progress", json={"chunk_index": 2, "verified": True}, headers=h
        )
        reader = await c.get(url)
    assert jumped.json()["verified_chunk"] == 0 and jumped.json()["current_chunk"] == 2
    # 마지막으로 본 쪽(3쪽)이 아니라 다 읽은 다음 쪽(2쪽 = index 1)에서 연다
    assert 'data-start="1"' in reader.text and 'data-verified="0"' in reader.text


async def test_jumping_away_and_back_still_lets_you_read_in_order(api, clock):
    async with api(upstream) as c:
        await signup(c)
        _, book_id, h = await _open(c)
        await read_chunk(c, book_id, 0, h["X-CSRF-Token"], clock)
        await c.put(f"/api/v1/books/{book_id}/progress", json={"chunk_index": 2}, headers=h)
        r = await read_chunk(c, book_id, 1, h["X-CSRF-Token"], clock)
    assert r["verified_chunk"] == 1


async def test_fresh_book_starts_at_first_page(api):
    async with api(upstream) as c:
        await signup(c)
        url, _, _ = await _open(c)
        reader = await c.get(url)
    assert 'data-start="0"' in reader.text and 'id="jump"' in reader.text and 'id="back"' in reader.text


async def test_chunk_dwell_is_flat_15s_and_server_decided(api, clock):
    async with api(upstream) as c:
        await signup(c)
        _, book_id, h = await _open(c)
        chunk = (await c.get(f"/api/v1/books/{book_id}/chunks/0")).json()
        need = chunk["min_dwell_ms"]
        await c.put(f"/api/v1/books/{book_id}/progress", json={"chunk_index": 0}, headers=h)
        clock((need - 1000) / 60_000)  # 1초 모자람
        early = await c.put(
            f"/api/v1/books/{book_id}/progress", json={"chunk_index": 0, "verified": True}, headers=h
        )
        clock(2 / 60)
        ok = await c.put(
            f"/api/v1/books/{book_id}/progress", json={"chunk_index": 0, "verified": True}, headers=h
        )
    assert need == PAGE_DWELL_MS == 15_000
    assert early.json()["verified_chunk"] == -1
    assert ok.json()["verified_chunk"] == 0
