import httpx
import pytest

from app.sources.base import SourceError, pick_isbn13
from app.sources.google_books import GoogleBooksSource
from app.sources.gutendex import GutendexSource, clean_gutenberg_text
from app.sources.kakao import KakaoSource
from app.sources.naver import NaverSource
from app.sources.wikisource import WikisourceSource, html_to_text
from tests.conftest import mock_client


def test_pick_isbn13():
    assert pick_isbn13("8936433598 9788936433598") == "9788936433598"
    assert pick_isbn13("978-89-364-3359-8") == "9788936433598"
    assert pick_isbn13("8936433598") is None
    assert pick_isbn13(None) is None


async def test_kakao_parses_documents_and_sends_key():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "documents": [
                    {
                        "title": "봄봄",
                        "authors": ["김유정"],
                        "isbn": "8936433598 9788936433598",
                        "thumbnail": "",
                        "url": "https://book.kakao/x",
                    }
                ]
            },
        )

    [hit] = await KakaoSource(mock_client(handler), "KEY").search("봄봄")
    assert seen["auth"] == "KakaoAK KEY"
    assert (hit.isbn13, hit.external_id, hit.cover_url) == ("9788936433598",) * 2 + (None,)
    assert hit.has_fulltext is False


async def test_naver_strips_markup_and_splits_authors():
    def handler(req):
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "<b>봄봄</b> &amp; 동백꽃",
                        "author": "김유정^엮은이",
                        "isbn": "9788936433598",
                        "image": "https://img",
                        "link": "https://naver/x",
                    }
                ]
            },
        )

    [hit] = await NaverSource(mock_client(handler), "id", "secret").search("봄봄")
    assert hit.title == "봄봄 & 동백꽃"
    assert hit.authors == ("김유정", "엮은이")


async def test_google_books_picks_isbn13():
    def handler(req):
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "g1",
                        "volumeInfo": {
                            "title": "Spring",
                            "authors": ["Kim"],
                            "language": "en",
                            "industryIdentifiers": [
                                {"type": "ISBN_10", "identifier": "1"},
                                {"type": "ISBN_13", "identifier": "9781234567897"},
                            ],
                        },
                    }
                ]
            },
        )

    [hit] = await GoogleBooksSource(mock_client(handler)).search("spring")
    assert hit.isbn13 == "9781234567897"
    assert hit.cover_url is None


GUTENBERG_RAW = """Header junk
*** START OF THE PROJECT GUTENBERG EBOOK ALICE ***
Alice was beginning
to get very tired.

So she was considering.
*** END OF THE PROJECT GUTENBERG EBOOK ALICE ***
License junk"""

GUTENDEX_BOOK = {
    "id": 11,
    "title": "Alice",
    "authors": [{"name": "Carroll, Lewis"}],
    "languages": ["en"],
    "formats": {
        "text/plain; charset=us-ascii": "https://g/11.txt",
        "text/plain; charset=utf-8": "https://g/11-0.txt",
        "image/jpeg": "https://g/11.jpg",
    },
}


def test_clean_gutenberg_text():
    assert clean_gutenberg_text(GUTENBERG_RAW) == (
        "Alice was beginning to get very tired.\n\nSo she was considering."
    )


async def test_gutendex_fetch_prefers_utf8_plain_text():
    def handler(req):
        if req.url.path == "/books/11":
            return httpx.Response(200, json=GUTENDEX_BOOK)
        if req.url.path == "/11-0.txt":
            return httpx.Response(200, text=GUTENBERG_RAW)
        return httpx.Response(404)

    meta, text = await GutendexSource(mock_client(handler)).fetch_book("11")
    assert meta.has_fulltext and meta.language == "en"
    assert text.startswith("Alice was beginning")


async def test_gutendex_rejects_non_numeric_id():
    with pytest.raises(SourceError):
        await GutendexSource(mock_client(lambda r: httpx.Response(500))).fetch_book("../x")


WIKI_HTML = """<div class="mw-parser-output">
<table><tr><td>머리말 틀</td></tr></table>
<h2>본문<span class="mw-editsection">[편집]</span></h2>
<p>"장인님! 인제 저……"<sup class="reference">[1]</sup></p>
<p>내가 이렇게   뒤통수를 긁고,<br/>나이가 찼으니</p>
<p>   </p>
<ol class="references"><li>각주</li></ol>
</div>"""


def test_wikisource_html_to_text_removes_noise():
    assert html_to_text(WIKI_HTML) == '"장인님! 인제 저……"\n\n내가 이렇게 뒤통수를 긁고,\n나이가 찼으니'


async def test_wikisource_search_and_fetch():
    def handler(req):
        action = req.url.params["action"]
        if action == "query":
            return httpx.Response(200, json={"query": {"search": [{"title": "봄봄"}]}})
        return httpx.Response(200, json={"parse": {"title": "봄봄", "text": WIKI_HTML}})

    src = WikisourceSource(mock_client(handler))
    [hit] = await src.search("봄봄")
    assert hit.has_fulltext and hit.external_id == "봄봄" and hit.language == "ko"
    meta, text = await src.fetch_book("봄봄")
    assert meta.title == "봄봄" and "장인님" in text


async def test_wikisource_missing_page_raises():
    def handler(req):
        return httpx.Response(200, json={"error": {"code": "missingtitle"}})

    with pytest.raises(SourceError, match="missingtitle"):
        await WikisourceSource(mock_client(handler)).fetch_book("없는문서")


async def test_metadata_sources_do_not_provide_fulltext():
    with pytest.raises(SourceError):
        await KakaoSource(mock_client(lambda r: httpx.Response(200)), "k").fetch_book("x")
