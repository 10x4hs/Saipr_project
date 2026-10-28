from tests.test_api import upstream


async def test_home_lists_featured_shelf(api):
    async with api(upstream) as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert "봄봄" in r.text and "/open/wikisource/%EB%B4%84%EB%B4%84" in r.text


async def test_open_imports_then_reader_renders(api):
    async with api(upstream) as c:
        r = await c.get("/open/wikisource/봄봄")
        assert r.status_code == 303
        reader = await c.get(r.headers["location"])
        again = await c.get("/open/wikisource/봄봄")
    assert reader.status_code == 200
    assert 'data-total="' in reader.text and "봄봄" in reader.text
    assert again.headers["location"] == r.headers["location"]  # 두 번째는 캐시


async def test_open_rejects_metadata_only_source(api):
    async with api(upstream) as c:
        r = await c.get("/open/google_books/abc")
    assert r.status_code == 400


async def test_search_page_separates_readable(api):
    async with api(upstream) as c:
        r = await c.get("/search", params={"q": "봄봄"})
    assert r.status_code == 200
    assert "바로 읽기" in r.text


async def test_unknown_book_is_404(api):
    async with api(upstream) as c:
        r = await c.get("/books/999")
    assert r.status_code == 404


async def test_static_assets_served(api):
    async with api(upstream) as c:
        r = await c.get("/static/reader.js")
    assert r.status_code == 200
