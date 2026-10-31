from tests.conftest import read_chunk, signup
from tests.test_api import upstream


async def test_anonymous_sees_landing_and_app_pages_redirect_to_login(api):
    async with api(upstream) as c:
        landing = await c.get("/")
        library = await c.get("/library")
    assert landing.status_code == 200 and "무료로 시작하기" in landing.text
    assert library.status_code == 303 and library.headers["location"] == "/login?next=/library"


async def test_home_is_3d_and_explore_has_the_shelves(api):
    async with api(upstream) as c:
        await signup(c, nickname="지현")
        home = await c.get("/")
        explore = await c.get("/discover")
        grid = await c.get("/discover", params={"g": "all"})
    assert home.status_code == 200 and "지현님" in home.text and 'class="hx-book"' in home.text
    assert "목록으로 보기" not in home.text  # 보기 전환은 없어지고 목록은 탐색으로
    assert "오늘의 추천" in explore.text and "단편소설" in explore.text and "서점 · 유명한 책" in explore.text
    assert grid.text.count('class="card"') > 800


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


async def test_store_book_links_to_aladin_and_upload(api):
    from app.web import STORE

    item = STORE[0]
    async with api(upstream) as c:
        await signup(c)
        page = await c.get(f"/store/{item['id']}")
        shelf = await c.get("/discover", params={"g": "서점"})
        form = await c.get("/upload", params={"store": item["id"]})
        token = form.text.split('name="csrf" value="')[1].split('"')[0]
        up = await c.post(
            "/upload",
            files={"file": ("mybook.txt", ("가나다라 마바사 " * 30).encode(), "text/plain")},
            data={"csrf": token, "store": item["id"]},
        )
        library = await c.get("/library")
        missing = await c.get("/store/0")
    assert page.status_code == 200 and item["url"].replace("&", "&amp;") in page.text and "DRM" in page.text
    assert shelf.text.count('class="card"') == len(STORE)
    assert "이 책의 파일을 올려요" in form.text
    # 올린 책에 서점 표지가 붙는다 (목록에서는 같은 표지의 작은 판)
    assert up.status_code == 303 and item["cover"].rsplit("/", 1)[1] in library.text
    assert missing.status_code == 404


def test_catalog_has_no_duplicate_titles():
    from app.web import CATALOG

    keys = [(b["title"].strip().lower(), (b.get("author") or "").strip().lower()) for b in CATALOG]
    assert len(keys) == len(set(keys))


async def test_profile_nickname_and_photo(api):
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 2000
    async with api(upstream) as c, api(upstream) as other:
        await signup(c, email="me@example.com", nickname="처음이름")
        page = await c.get("/me")
        token = page.text.split('name="csrf" value="')[1].split('"')[0]
        r = await c.post(
            "/me/profile",
            data={"csrf": token, "nickname": "  새이름 "},
            files={"photo": ("a.jpg", jpeg, "image/jpeg")},
        )
        me = await c.get("/me")
        src = me.text.split('<span class="avatar xl"><img src="')[1].split('"')[0]
        img = await c.get(src)
        bad = await c.post(
            "/me/profile",
            data={"csrf": token, "nickname": "새이름"},
            files={"photo": ("a.png", b"\x89PNG....", "image/png")},
        )
        empty = await c.post("/me/profile", data={"csrf": token, "nickname": "   "})
        anon = await other.get(src)
    assert r.headers["location"] == "/me?saved=1" and "새이름" in me.text
    assert img.status_code == 200 and img.content == jpeg and img.headers["content-type"] == "image/jpeg"
    assert "error=" in bad.headers["location"] and "error=" in empty.headers["location"]
    assert anon.status_code == 303  # 로그인해야 볼 수 있다


async def test_store_page_shows_review_videos(api):
    from app.web import STORE, VIDEOS

    item = next(b for b in STORE if VIDEOS.get(f"store:{b['id']}"))
    async with api(upstream) as c:
        await signup(c)
        page = await c.get(f"/store/{item['id']}")
    first = VIDEOS[f"store:{item['id']}"][0]
    assert "이 책을 소개하는 영상" in page.text and f'data-yt="{first["id"]}"' in page.text


async def test_brand_is_haedok_everywhere(api):
    async with api(upstream) as c:
        landing = await c.get("/")
        login = await c.get("/login")
        await signup(c)
        home = await c.get("/")
    for page in (landing, login, home):
        assert "偕讀" in page.text and "해독" in page.text
        assert "함께읽기" not in page.text
    assert 'class="side-brand"' in home.text  # 넓은 화면 사이드바의 로고


async def test_me_page_title_has_no_script(api):
    """사진 고르기 스크립트가 <title> 안에 들어가 실행되지 않던 버그."""
    async with api(upstream) as c:
        await signup(c)
        me = await c.get("/me")
    title = me.text.split("<title>", 1)[1].split("</title>", 1)[0]
    assert "<script" not in title and title.startswith("내 정보")
    assert "photoPick" in me.text.split("</title>", 1)[1].split("<script>")[-1]


async def test_reader_has_side_column_and_wide_pages_are_marked(api):
    async with api(upstream) as c:
        await signup(c)
        r = await c.get("/open/wikisource/봄봄")
        reader = await c.get(r.headers["location"])
        discover = await c.get("/discover")
        me = await c.get("/me")
    assert 'id="side"' in reader.text and 'id="sideFriends"' in reader.text
    assert 'class="content wide"' in discover.text and 'class="content split"' in me.text
