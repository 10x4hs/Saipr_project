import asyncio

import httpx

from app.services.search import search_all
from app.sources.base import BookMeta, BookSource


class FakeSource(BookSource):
    def __init__(self, name, result=(), exc=None, delay=0.0):
        super().__init__(httpx.AsyncClient())
        self.name, self._result, self._exc, self._delay = name, list(result), exc, delay

    async def search(self, query, limit=10):
        await asyncio.sleep(self._delay)
        if self._exc:
            raise self._exc
        return self._result


def meta(source, isbn=None, fulltext=False, title="t"):
    return BookMeta(source=source, external_id=isbn or title, title=title, isbn13=isbn, has_fulltext=fulltext)


async def test_merges_same_isbn_keeping_priority_order():
    res = await search_all(
        [
            FakeSource("kakao", [meta("kakao", "9788936433598")]),
            FakeSource("naver", [meta("naver", "9788936433598"), meta("naver", "9780000000002")]),
        ],
        "q",
    )
    assert [h.meta.source for h in res.hits] == ["kakao", "naver"]
    assert res.hits[0].sources == ["kakao", "naver"]
    assert res.errors == {}


async def test_partial_failure_returns_other_results_without_leaking_message():
    secret = httpx.HTTPStatusError("https://x?key=SECRET", request=None, response=None)
    res = await search_all(
        [
            FakeSource("google_books", exc=secret),
            FakeSource("wikisource", [meta("wikisource", fulltext=True)]),
        ],
        "q",
    )
    assert len(res.hits) == 1
    assert res.errors == {"google_books": "HTTPStatusError"}


async def test_slow_source_times_out():
    res = await search_all([FakeSource("naver", [meta("naver")], delay=1)], "q", timeout=0.05)
    assert res.hits == [] and res.errors == {"naver": "TimeoutError"}


async def test_fulltext_flag_only_for_public_domain_sources():
    res = await search_all([FakeSource("kakao", [meta("kakao", fulltext=True)])], "q")
    assert res.hits[0].meta.has_fulltext is False
