import io
import zipfile

import httpx
import pytest

from app.services.uploads import fingerprint, parse_upload
from app.sources.base import SourceError
from app.sources.gutendex import GutendexSource
from tests.conftest import mock_client, signup
from tests.test_api import upstream

BODY = "옛날 옛적에 한 마을이 있었다. " * 20


def make_epub(chapters: list[str], *, drm: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        items = "".join(f'<item id="c{i}" href="c{i}.xhtml"/>' for i in range(len(chapters)))
        refs = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
        z.writestr(
            "OEBPS/content.opf",
            '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>'
            "<dc:title>시험 책</dc:title><dc:creator>홍길동</dc:creator></metadata>"
            f"<manifest>{items}</manifest><spine>{refs}</spine></package>",
        )
        for i, text in enumerate(chapters):
            z.writestr(f"OEBPS/c{i}.xhtml", f"<html><body><p>{text}</p></body></html>")
        if drm:
            z.writestr("META-INF/encryption.xml", "<encryption/>")
    return buf.getvalue()


def test_epub_reads_spine_in_order_with_metadata():
    book = parse_upload("x.epub", make_epub(["첫 장 " + BODY, "둘째 장 " + BODY]))
    assert (book.title, book.author, book.language) == ("시험 책", "홍길동", "ko")
    assert book.text.index("첫 장") < book.text.index("둘째 장")


def test_drm_epub_is_refused():
    with pytest.raises(SourceError, match="DRM"):
        parse_upload("x.epub", make_epub([BODY], drm=True))


def test_txt_accepts_cp949_and_uses_filename_as_title():
    book = parse_upload("봄날.txt", BODY.encode("cp949"))
    assert book.title == "봄날" and "마을" in book.text


@pytest.mark.parametrize("name,data", [("x.docx", b"abc"), ("x.txt", b"short"), ("x.epub", b"not a zip")])
def test_bad_files_are_refused(name, data):
    with pytest.raises(SourceError):
        parse_upload(name, data)


def test_fingerprint_ignores_spacing_and_punctuation():
    assert fingerprint("봄, 봄!\n\n장인님") == fingerprint("봄 봄  장인님")


async def _upload(c, files):
    html = (await c.get("/upload")).text
    token = html.split('name="csrf" value="')[1].split('"')[0]
    return await c.post("/upload", files=files, data={"csrf": token})


async def test_upload_is_private_to_its_owner(api):
    files = {"file": ("비밀일기장.txt", BODY.encode(), "text/plain")}
    async with api(upstream) as owner, api(upstream) as stranger:
        await signup(owner, email="owner@example.com")
        await signup(stranger, email="stranger@example.com")
        r = await _upload(owner, files)
        assert r.status_code == 303
        url = r.headers["location"]
        book_id = url.rsplit("/", 1)[1]
        assert (await owner.get(url)).status_code == 200
        assert (await owner.get(f"/api/v1/books/{book_id}/chunks/0")).status_code == 200
        assert (await stranger.get(url)).status_code == 404
        assert (await stranger.get(f"/api/v1/books/{book_id}/chunks/0")).status_code == 404
        again = await _upload(owner, files)
        assert again.headers["location"] == url  # 같은 책을 다시 올려도 하나만
        assert "비밀일기장" in (await owner.get("/library")).text
        assert "비밀일기장" not in (await stranger.get("/library")).text


async def test_upload_error_is_shown_on_page(api):
    async with api(upstream) as c:
        await signup(c)
        r = await _upload(c, {"file": ("x.docx", b"abc", "application/octet-stream")})
    assert r.status_code == 422 and "EPUB, PDF, TXT" in r.text


async def test_gutendex_outage_falls_back_to_gutenberg_mirror():
    raw = "Title: Tiny Tale\nAuthor: A. Writer\n*** START OF THE PROJECT GUTENBERG EBOOK ***\nOnce upon\na time.\n\nThe end.\n*** END OF THE PROJECT GUTENBERG EBOOK ***"

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "gutendex.com":
            return httpx.Response(503)
        return httpx.Response(200, text=raw)

    meta, text = await GutendexSource(mock_client(handler)).fetch_book("42")
    assert (meta.title, meta.authors) == ("Tiny Tale", ("A. Writer",))
    assert text == "Once upon a time.\n\nThe end."
