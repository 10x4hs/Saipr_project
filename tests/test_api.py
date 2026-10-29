import re

import httpx

from tests.conftest import signup
from tests.test_sources import WIKI_HTML


async def login_headers(c) -> dict:
    """가입해서 로그인하고, API 호출에 쓸 CSRF 헤더를 돌려준다."""
    await signup(c, email=f"api{id(c)}@example.com")
    token = re.search(r'<meta name="csrf" content="([^"]+)"', (await c.get("/")).text).group(1)
    return {"X-CSRF-Token": token}


LONG_HTML = "".join(f"<p>{i}번째 문단. " + "가" * 500 + "</p>" for i in range(6))


def upstream(req: httpx.Request) -> httpx.Response:
    host = req.url.host
    if host == "ko.wikisource.org":
        if req.url.params["action"] == "query":
            return httpx.Response(200, json={"query": {"search": [{"title": "봄봄"}]}})
        page = req.url.params["page"]
        html = LONG_HTML if page == "긴글" else WIKI_HTML
        return httpx.Response(200, json={"parse": {"title": page, "text": html}})
    if host == "gutendex.com":
        return httpx.Response(200, json={"results": []})
    if host == "www.googleapis.com":
        return httpx.Response(503)
    return httpx.Response(404)


async def test_health(api):
    async with api(upstream) as c:
        r = await c.get("/health")
    assert r.json() == {"status": "ok"}


async def test_search_reports_partial_errors(api):
    async with api(upstream) as c:
        r = await c.get("/api/v1/books/search", params={"q": "봄봄"})
    body = r.json()
    assert r.status_code == 200
    assert [(i["source"], i["has_fulltext"]) for i in body["items"]] == [("wikisource", True)]
    assert body["errors"] == {"google_books": "HTTPStatusError"}


async def test_import_then_read_chunks(api):
    async with api(upstream) as c, api(upstream) as anon:
        anonymous_import = await anon.post(
            "/api/v1/books/import", json={"source": "wikisource", "external_id": "긴글"}
        )
        assert anonymous_import.status_code == 401  # 가져오기는 로그인한 사람만
        h = await login_headers(c)
        r = await c.post(
            "/api/v1/books/import", json={"source": "wikisource", "external_id": "긴글"}, headers=h
        )
        book = r.json()
        assert r.status_code == 200 and book["total_chunks"] == 3
        again = await c.post(
            "/api/v1/books/import", json={"source": "wikisource", "external_id": "긴글"}, headers=h
        )
        assert again.json()["id"] == book["id"]  # 캐시: 중복 생성 없음

        anonymous = await anon.get(f"/api/v1/books/{book['id']}/chunks/0")
        assert anonymous.status_code == 404  # 본문은 로그인한 사용자만

        chunk = (await c.get(f"/api/v1/books/{book['id']}/chunks/0")).json()
        assert chunk["total_chunks"] == 3
        assert chunk["text"].startswith("0번째 문단.")
        assert chunk["min_dwell_ms"] > 0

        missing = await c.get(f"/api/v1/books/{book['id']}/chunks/3")
        assert missing.status_code == 404


async def test_import_rejects_non_public_domain_source(api):
    async with api(upstream) as c:
        h = await login_headers(c)
        r = await c.post(
            "/api/v1/books/import", json={"source": "google_books", "external_id": "g1"}, headers=h
        )
    assert r.status_code == 400


async def test_import_upstream_failure_is_502(api):
    def down(req):
        return httpx.Response(500)

    async with api(down) as c:
        h = await login_headers(c)
        r = await c.post(
            "/api/v1/books/import", json={"source": "wikisource", "external_id": "봄봄"}, headers=h
        )
    assert r.status_code == 502
