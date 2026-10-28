from tests.test_api import upstream


async def test_home_lists_featured_shelf(api):
    async with api(upstream) as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert "단편소설" in r.text and "/shelf/" in r.text


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


async def test_shelf_page_lists_whole_genre(api):
    from app.web import SHELVES

    async with api(upstream) as c:
        r = await c.get("/shelf/단편소설")
        missing = await c.get("/shelf/없는장르")
    assert r.status_code == 200 and r.text.count('class="book"') == len(SHELVES["단편소설"])
    assert missing.status_code == 404


def test_catalog_entries_are_well_formed():
    from app.web import CATALOG

    assert len(CATALOG) > 300
    assert {b["source"] for b in CATALOG} <= {"wikisource", "gutendex"}
    assert len({(b["source"], b["id"]) for b in CATALOG}) == len(CATALOG)
