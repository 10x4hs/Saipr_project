"""책 목록 · 책 소개(위키백과 요약 캐시) — 외부 호출은 모두 MockTransport."""

import json
from urllib.parse import unquote

import httpx
from sqlalchemy import update

from app import models
from app.services import book_info
from app.services.book_info import summary_url
from app.services.catalog import COVER_COLORS, cover_color
from tests.conftest import make_book, set_position, token_signup


def wiki(pages: dict[str, dict], calls: list[str] | None = None, fail: bool = False):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "ko.wikipedia.org"
        title = unquote(req.url.path.rsplit("/", 1)[1]).replace("_", " ")
        if calls is not None:
            calls.append(title)
        if fail:
            raise httpx.ConnectError("offline", request=req)
        page = pages.get(title)
        if page is None:
            return httpx.Response(
                404, json={"type": "https://mediawiki.org/wiki/HyperSwitch/errors/not_found"}
            )
        return httpx.Response(200, content=json.dumps(page))

    return handler


def page(extract: str, url: str, kind: str = "standard") -> dict:
    return {"type": kind, "extract": extract, "content_urls": {"desktop": {"page": url}}}


PAGES = {
    "감자": page("감자는 가짓과의 여러해살이풀이다.", "https://ko.wikipedia.org/wiki/감자"),  # 동명이의 함정
    "감자 (소설)": page(
        "〈감자〉는 1925년 김동인의 단편 소설이다.", "https://ko.wikipedia.org/wiki/감자_(소설)"
    ),
    "김동인": page("김동인은 일제강점기의 소설가이다.", "https://ko.wikipedia.org/wiki/김동인"),
}


async def gamja(session_factory) -> int:
    book_id = await make_book(session_factory, [["싸움, 간통, 살인."], ["복녀는 죽었다."]], title="감자")
    async with session_factory() as s:
        await s.execute(update(models.Book).values(author="김동인", genre="소설"))
        await s.commit()
    return book_id


def test_summary_url_and_cover_color():
    assert (
        summary_url("감자 (소설)")
        == "https://ko.wikipedia.org/api/rest_v1/page/summary/%EA%B0%90%EC%9E%90_%28%EC%86%8C%EC%84%A4%29"
    )
    assert cover_color(7) == cover_color(7) and cover_color(7) in COVER_COLORS


async def test_info_fetches_once_and_caches(api, session_factory):
    book = await gamja(session_factory)
    calls: list[str] = []
    # api()는 마지막에 만든 클라이언트의 handler로 외부 호출을 흉내 낸다 — 위키 handler를 마지막에
    async with api() as friend_c, api(wiki(PAGES, calls)) as c:
        await token_signup(c, "독자")
        friend = await token_signup(friend_c, "친구")
        await set_position(session_factory, friend["id"], book, 0)
        await c.post(f"/api/v1/users/{friend['id']}/follow")

        r = await c.get(f"/api/v1/books/{book}/info")
        assert r.status_code == 200, r.text
        info = r.json()
        assert info["description"].startswith("〈감자〉는 1925년")  # '감자'(채소) 문서는 건너뛴다
        assert info["author_bio"] == "김동인은 일제강점기의 소설가이다."
        assert info["wiki_url"] == "https://ko.wikipedia.org/wiki/감자_(소설)"
        assert info["source_url"] == "https://ko.wikisource.org/wiki/%EA%B0%90%EC%9E%90"
        assert info["total_chars"] == len("싸움, 간통, 살인.") + len("복녀는 죽었다.")
        assert info["genre"] == "소설" and info["cover_color"] == cover_color(book) and info["readers"] == 1
        assert info["friends_reading"] == [
            {"id": friend["id"], "nickname": "친구", "avatar_color": friend["avatar_color"]}
        ]
        assert info["my_entry"] is None

        n = len(calls)
        await c.put(f"/api/v1/library/{book}", json={"shelf": "want"})
        info = (await c.get(f"/api/v1/books/{book}/info")).json()
        assert len(calls) == n  # DB 캐시 — 다시 부르지 않는다
        assert info["my_entry"]["shelf"] == "want" and info["readers"] == 2


async def test_info_offline_returns_nulls_and_retries_later(api, session_factory):
    book = await gamja(session_factory)
    calls: list[str] = []
    async with api(wiki(PAGES, calls, fail=True)) as c:
        await token_signup(c, "오프라인")
        r = await c.get(f"/api/v1/books/{book}/info")
        assert r.status_code == 200
        assert (r.json()["description"], r.json()["author_bio"], r.json()["wiki_url"]) == (None, None, None)
    async with session_factory() as s:
        assert (await s.get(models.Book, book)).info_fetched_at is None  # 실패는 캐시하지 않는다
    async with api(wiki(PAGES)) as c:
        await token_signup(c, "온라인")
        # 방금 실패했으면 잠시(10분)는 다시 묻지 않는다 — 책 화면이 매번 기다리지 않게
        assert (await c.get(f"/api/v1/books/{book}/info")).json()["description"] is None
        book_info._failed_at.clear()  # 10분이 지났다
        assert (await c.get(f"/api/v1/books/{book}/info")).json()["description"] is not None


async def test_info_tolerates_garbage_and_missing_pages(api, session_factory):
    book = await make_book(session_factory, [["본문"]], title="없는 책")

    def garbage(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json")

    async with api(garbage) as c:
        await token_signup(c, "a")
        r = await c.get(f"/api/v1/books/{book}/info")
        assert r.status_code == 200 and r.json()["description"] is None
    other = await make_book(session_factory, [["본문"]], title="동명이의 책")
    async with api(wiki({"동명이의 책": page("동명이의", "https://x", kind="disambiguation")})) as c:
        await token_signup(c, "b")
        assert (await c.get(f"/api/v1/books/{other}/info")).json()["description"] is None
        assert (await c.get("/api/v1/books/9999/info")).status_code == 404


async def test_list_books_sort_genre_and_readers(api, session_factory):
    poem = await make_book(session_factory, [["시"]], title="진달래꽃")
    novel = await make_book(session_factory, [["소설"]], title="감자")
    plain = await make_book(session_factory, [["?"]], title="무장르")
    async with session_factory() as s:
        await s.execute(update(models.Book).where(models.Book.id == poem).values(genre="시"))
        await s.execute(update(models.Book).where(models.Book.id == novel).values(genre="소설"))
        await s.commit()
    async with api() as a, api() as b:
        await token_signup(a, "가")
        await token_signup(b, "나")
        for c in (a, b):
            await c.put(f"/api/v1/library/{poem}", json={"shelf": "want"})
        await a.put(f"/api/v1/library/{novel}", json={"shelf": "want"})

        popular = (await a.get("/api/v1/books")).json()
        assert [(x["id"], x["readers"]) for x in popular] == [(poem, 2), (novel, 1), (plain, 0)]
        assert set(popular[0]) == {
            "id",
            "source",
            "external_id",
            "title",
            "author",
            "genre",
            "has_fulltext",
            "total_chunks",
            "cover_url",
            "cover_color",
            "readers",
        }
        assert [x["id"] for x in (await a.get("/api/v1/books", params={"sort": "new"})).json()] == [
            plain,
            novel,
            poem,
        ]
        assert [x["id"] for x in (await a.get("/api/v1/books", params={"genre": "시"})).json()] == [poem]
        assert (await a.get("/api/v1/books", params={"genre": "만화"})).status_code == 422
        assert len((await a.get("/api/v1/books", params={"limit": 1})).json()) == 1


async def test_bundled_samples_load_idempotently_offline(api, session_factory):
    from sqlalchemy import func, select

    from app.seed import SAMPLES, load_samples

    items = json.loads(SAMPLES.read_text(encoding="utf-8"))
    assert len(items) >= 13 and len({i["external_id"] for i in items}) == len(items)
    assert {i["genre"] for i in items} == {"소설", "시", "수필"}
    for i in items:
        assert len(i["text"]) >= 100 and i["license"].startswith("Public domain"), i["title"]
        assert i["origin"].startswith("https://ko.wikisource.org/wiki/")

    async with session_factory() as s:
        await load_samples(s)
        await load_samples(s)  # 두 번 돌려도 같은 결과
        assert await s.scalar(select(func.count()).select_from(models.Book)) == len(items)
        books = list(await s.scalars(select(models.Book)))
    assert all(b.genre and b.total_chunks > 0 for b in books)
    assert sum(1 for b in books if b.description) >= len(items) - 2
    assert all(b.info_fetched_at is not None for b in books if b.description or b.author_bio)

    # 미리 받아 둔 요약이 있으니 책 소개 화면은 외부를 부르지 않는다
    calls: list[str] = []
    async with api(wiki({}, calls)) as c:
        await token_signup(c, "시연")
        gamja_id = next(b.id for b in books if b.title == "감자")
        info = (await c.get(f"/api/v1/books/{gamja_id}/info")).json()
    assert calls == [] and "김동인" in info["description"] and info["genre"] == "소설"
