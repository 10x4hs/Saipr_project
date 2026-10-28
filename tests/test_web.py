from tests.conftest import read_chunk, signup
from tests.test_api import upstream


async def test_anonymous_sees_landing_and_app_pages_redirect_to_login(api):
    async with api(upstream) as c:
        landing = await c.get("/")
        library = await c.get("/library")
    assert landing.status_code == 200 and "무료로 시작하기" in landing.text
    assert library.status_code == 303 and library.headers["location"] == "/login?next=/library"


async def test_home_shows_greeting_and_shelves(api):
    async with api(upstream) as c:
        await signup(c, nickname="지현")
        r = await c.get("/")
    assert r.status_code == 200
    assert "지현님" in r.text and "오늘의 추천" in r.text and "단편소설" in r.text


async def test_open_shelves_book_and_reader_resumes(api):
    async with api(upstream) as c:
        await signup(c)
        r = await c.get("/open/wikisource/봄봄")
        assert r.status_code == 303
        reader = await c.get(r.headers["location"])
        again = await c.get("/open/wikisource/봄봄")
        library = await c.get("/library")
    assert reader.status_code == 200 and 'data-start="0"' in reader.text
    assert again.headers["location"] == r.headers["location"]  # 두 번째는 캐시
    assert "봄봄" in library.text  # 펼친 책은 서재에 '읽는 중'으로


async def test_progress_is_saved_and_resumed(api, clock):
    async with api(upstream) as c:
        await signup(c)
        url = (await c.get("/open/wikisource/긴글")).headers["location"]
        book_id = url.rsplit("/", 1)[1]
        token = (await c.get(url)).text.split('data-csrf="')[1].split('"')[0]
        await read_chunk(c, book_id, 0, token, clock)
        await read_chunk(c, book_id, 1, token, clock)
        r = await c.put(
            f"/api/v1/books/{book_id}/progress", json={"chunk_index": 2}, headers={"X-CSRF-Token": token}
        )
        assert r.json() == {"current_chunk": 2, "verified_chunk": 1, "progress_pct": 67, "shelf": "reading"}
        clock(10)
        done = await c.put(
            f"/api/v1/books/{book_id}/progress",
            json={"chunk_index": 2, "verified": True},
            headers={"X-CSRF-Token": token},
        )
        reader = await c.get(url)
    assert done.json()["shelf"] == "done"
    assert 'data-start="2"' in reader.text


async def test_skimming_is_not_credited(api, clock):
    """GOAL #6: 최소 체류시간을 못 채운 쪽은 진행률·레이스 점수에 0."""
    async with api(upstream) as c:
        await signup(c)
        url = (await c.get("/open/wikisource/긴글")).headers["location"]
        book_id = url.rsplit("/", 1)[1]
        token = (await c.get(url)).text.split('data-csrf="')[1].split('"')[0]
        h = {"X-CSRF-Token": token}
        await c.put(f"/api/v1/books/{book_id}/progress", json={"chunk_index": 0}, headers=h)
        clock(0.01)  # 0.6초 만에 '다 읽음'
        quick = await c.put(
            f"/api/v1/books/{book_id}/progress", json={"chunk_index": 0, "verified": True}, headers=h
        )
        never_opened = await c.put(
            f"/api/v1/books/{book_id}/progress", json={"chunk_index": 1, "verified": True}, headers=h
        )
    assert quick.json()["verified_chunk"] == -1 and quick.json()["progress_pct"] == 0
    assert never_opened.json()["verified_chunk"] == -1  # 펼친 적 없는 쪽, 순서를 건너뛴 쪽도 0


async def test_progress_requires_csrf(api):
    async with api(upstream) as c:
        await signup(c)
        url = (await c.get("/open/wikisource/봄봄")).headers["location"]
        r = await c.put(f"/api/v1/books/{url.rsplit('/', 1)[1]}/progress", json={"chunk_index": 0})
    assert r.status_code == 403


async def test_open_rejects_metadata_only_source(api):
    async with api(upstream) as c:
        await signup(c)
        r = await c.get("/open/google_books/abc")
    assert r.status_code == 400


async def test_search_page(api):
    async with api(upstream) as c:
        await signup(c)
        r = await c.get("/search", params={"q": "봄봄"})
    assert r.status_code == 200 and "서가에서 찾음" in r.text


async def test_unknown_book_is_404(api):
    async with api(upstream) as c:
        await signup(c)
        r = await c.get("/books/999")
    assert r.status_code == 404


async def test_discover_filters_by_genre(api):
    from app.web import SHELVES

    async with api(upstream) as c:
        await signup(c)
        r = await c.get("/discover", params={"g": "동화"})
        old = await c.get("/shelf/동화")
    assert r.status_code == 200 and r.text.count('class="card"') == len(SHELVES["동화"])
    assert old.status_code == 301


async def test_me_page_and_logout(api):
    async with api(upstream) as c:
        await signup(c, nickname="민우")
        me = await c.get("/me")
        token = me.text.split('name="csrf" value="')[1].split('"')[0]
        out = await c.post("/logout", data={"csrf": token})
        after = await c.get("/me")
    assert "민우" in me.text and "읽은 쪽" in me.text
    assert out.status_code == 303 and after.status_code == 303


async def test_static_assets_served(api):
    async with api(upstream) as c:
        r = await c.get("/static/reader.js")
    assert r.status_code == 200


def test_catalog_entries_are_well_formed():
    from app.web import CATALOG

    assert len(CATALOG) > 300
    assert {b["source"] for b in CATALOG} <= {"wikisource", "gutendex"}
    assert len({(b["source"], b["id"]) for b in CATALOG}) == len(CATALOG)
