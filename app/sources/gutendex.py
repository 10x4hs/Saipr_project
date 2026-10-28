import re
from typing import Any

import httpx

from app.sources.base import BookMeta, BookSource, SourceError

_START = re.compile(r"^\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*$", re.M | re.I)
_END = re.compile(r"^\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*$", re.M | re.I)
_BLANK_LINE = re.compile(r"\n\s*\n")
_HEADER_TITLE = re.compile(r"^Title:\s*(.+)$", re.M)
_HEADER_AUTHOR = re.compile(r"^Author:\s*(.+)$", re.M)


def _text_url(book: dict[str, Any]) -> str | None:
    """utf-8 평문을 우선, 없으면 아무 text/plain. zip 아카이브는 제외."""
    formats = book.get("formats") or {}
    plain = [(k, v) for k, v in formats.items() if k.startswith("text/plain") and not v.endswith(".zip")]
    plain.sort(key=lambda kv: "utf-8" not in kv[0])
    return plain[0][1] if plain else None


def clean_gutenberg_text(raw: str) -> str:
    """라이선스 머리말/꼬리말을 잘라내고, 하드랩된 줄을 문단 단위로 다시 잇는다."""
    text = raw.replace("\r\n", "\n")
    if m := _START.search(text):
        text = text[m.end() :]
    if m := _END.search(text):
        text = text[: m.start()]
    paragraphs = (" ".join(p.split()) for p in _BLANK_LINE.split(text))
    return "\n\n".join(p for p in paragraphs if p)


class GutendexSource(BookSource):
    """Project Gutenberg 비공식 REST API — 영문 퍼블릭 도메인 전문."""

    name = "gutendex"
    fulltext = True
    URL = "https://gutendex.com/books/"
    MIRROR = "https://www.gutenberg.org/cache/epub/"

    async def search(self, query: str, limit: int = 10) -> list[BookMeta]:
        data = await self._get_json(self.URL, params={"search": query})
        return [self._meta(b) for b in data.get("results", [])[:limit]]

    async def fetch_book(self, external_id: str) -> tuple[BookMeta, str]:
        if not external_id.isdigit():
            raise SourceError(f"invalid gutenberg id: {external_id!r}")
        try:
            book = await self._get_json(f"{self.URL}{external_id}")
        except httpx.HTTPError:
            return await self._fetch_direct(external_id)
        url = _text_url(book)
        if url is None:
            raise SourceError(f"gutenberg #{external_id} has no plain-text format")
        resp = await self.client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return self._meta(book), clean_gutenberg_text(resp.text)

    async def _fetch_direct(self, external_id: str) -> tuple[BookMeta, str]:
        """gutendex 장애 시 구텐베르크 원본 서버에서 평문을 직접 받는다."""
        resp = await self.client.get(f"{self.MIRROR}{external_id}/pg{external_id}.txt", follow_redirects=True)
        resp.raise_for_status()
        header = resp.text[:3000]
        title = m.group(1).strip() if (m := _HEADER_TITLE.search(header)) else f"Gutenberg #{external_id}"
        author = (m.group(1).strip(),) if (m := _HEADER_AUTHOR.search(header)) else ()
        meta = BookMeta(
            source=self.name,
            external_id=external_id,
            title=title,
            authors=author,
            language="en",
            has_fulltext=True,
            link=f"https://www.gutenberg.org/ebooks/{external_id}",
        )
        return meta, clean_gutenberg_text(resp.text)

    def _meta(self, b: dict[str, Any]) -> BookMeta:
        return BookMeta(
            source=self.name,
            external_id=str(b["id"]),
            title=b.get("title", ""),
            authors=tuple(a["name"] for a in b.get("authors", [])),
            cover_url=(b.get("formats") or {}).get("image/jpeg"),
            language=(b.get("languages") or [None])[0],
            has_fulltext=_text_url(b) is not None,
            link=f"https://www.gutenberg.org/ebooks/{b['id']}",
        )
