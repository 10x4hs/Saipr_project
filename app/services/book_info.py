"""책 소개 · 작가 소개 — 한국어 위키백과 요약 API를 받아 DB에 캐시한다.

GET https://ko.wikipedia.org/api/rest_v1/page/summary/{title}

- 받아 둔 값(info_fetched_at)이 있으면 다시 부르지 않는다. 아무것도 못 찾았으면 7일 뒤에 다시 시도한다.
- 네트워크 오류·시간 초과·이상한 응답은 조용히 넘어간다(null). 이 API가 5xx를 내는 일은 없어야 한다.
- 동명이의 문서(감자 → 채소)를 피하려고 작품 요약에는 작가 이름이,
  작가 요약에는 문인임을 뜻하는 낱말이 있어야 받는다.
- 위키백과 본문은 CC BY-SA 4.0이라 출처(wiki_url)를 함께 저장하고 화면에 표시한다.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import aware, utcnow
from app.models import Book

log = logging.getLogger(__name__)

SUMMARY_API = "https://ko.wikipedia.org/api/rest_v1/page/summary/"
RETRY_EMPTY_AFTER = timedelta(days=7)
FETCH_TIMEOUT = 5.0
MAX_TEXT = 2000
WRITER_WORDS = ("작가", "소설가", "시인", "문인", "문학", "수필가", "극작가", "평론가")
_WORK_SUFFIX = {"소설": ("소설",), "시": ("시",), "수필": ("수필",)}


def summary_url(title: str) -> str:
    return SUMMARY_API + quote(title.replace(" ", "_"), safe="")


def _first_author(author: str | None) -> str | None:
    if not author:
        return None
    name = author.split(",")[0].strip()
    return name or None


def work_candidates(book: Book) -> list[str]:
    """'감자'처럼 흔한 낱말이 제목이면 '감자 (소설)' 문서가 따로 있다. 장르 꼬리표를 먼저 시도한다."""
    suffixes = _WORK_SUFFIX.get(book.genre or "", ("소설", "시"))
    out = [f"{book.title} ({s})" for s in suffixes]
    if author := _first_author(book.author):
        out.append(f"{book.title} ({author})")
    out.append(book.title)
    return out


def author_candidates(book: Book) -> list[str]:
    author = _first_author(book.author)
    if author is None:
        return []
    return [author, f"{author} (작가)", f"{author} (소설가)", f"{author} (시인)"]


async def _summary(client: httpx.AsyncClient, title: str) -> dict | None:
    try:
        r = await client.get(summary_url(title), timeout=FETCH_TIMEOUT)
    except httpx.HTTPError as e:
        log.info("wikipedia summary %r failed: %s", title, type(e).__name__)
        raise
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("type") != "standard":
        return None  # 동명이의 문서 · 없는 문서
    extract = data.get("extract")
    if not isinstance(extract, str) or not extract.strip():
        return None
    return data


def _page_url(data: dict) -> str | None:
    url = ((data.get("content_urls") or {}).get("desktop") or {}).get("page")
    return url if isinstance(url, str) and url.startswith("https://") else None


async def _first_match(client: httpx.AsyncClient, titles: list[str], accept) -> dict | None:
    for title in titles:
        data = await _summary(client, title)
        if data is not None and accept(data["extract"]):
            return data
    return None


def needs_fetch(book: Book, now: datetime) -> bool:
    if book.info_fetched_at is None:
        return True
    empty = book.description is None and book.author_bio is None
    return empty and now - aware(book.info_fetched_at) >= RETRY_EMPTY_AFTER


# 위키백과가 느리거나 막혀도 책 화면이 오래 기다리지 않게
TOTAL_TIMEOUT = 6.0
FAIL_BACKOFF = timedelta(minutes=10)
_failed_at: dict[int, datetime] = {}
_locks: dict[int, asyncio.Lock] = {}


async def ensure_info(
    session: AsyncSession, client: httpx.AsyncClient, book: Book, now: datetime | None = None
) -> Book:
    """필요하면 위키백과 요약을 받아 저장한다. 실패해도 예외를 내지 않는다."""
    now = now or utcnow()
    if not needs_fetch(book, now):
        return book
    failed = _failed_at.get(book.id)
    if failed is not None and now - failed < FAIL_BACKOFF:
        return book  # 방금 실패했다 — 화면을 기다리게 하지 않는다
    lock = _locks.setdefault(book.id, asyncio.Lock())
    if lock.locked():
        return book  # 같은 책을 다른 요청이 받는 중
    async with lock:
        return await _fetch(session, client, book, now)


async def _fetch(session: AsyncSession, client: httpx.AsyncClient, book: Book, now: datetime) -> Book:
    author = _first_author(book.author)

    def is_work(extract: str) -> bool:
        return author is None or author in extract

    def is_writer(extract: str) -> bool:
        return any(w in extract for w in WRITER_WORDS)

    try:
        work, writer = await asyncio.wait_for(
            asyncio.gather(
                _first_match(client, work_candidates(book), is_work),
                _first_match(client, author_candidates(book), is_writer),
            ),
            TOTAL_TIMEOUT,
        )
        description = work["extract"].strip()[:MAX_TEXT] if work is not None else None
        bio = writer["extract"].strip()[:MAX_TEXT] if writer is not None else None
        url = (_page_url(work) if work is not None else None) or (
            _page_url(writer) if writer is not None else None
        )
    except (TimeoutError, httpx.HTTPError):
        # 오프라인 · 시간 초과 — 저장하지 않고, 잠시 뒤에 다시 시도한다
        _failed_at[book.id] = now
        return book
    except Exception:  # 응답 형식이 예상과 달라도 책 화면은 떠야 한다
        log.exception("wikipedia summary parse failed for book %s", book.id)
        _failed_at[book.id] = now
        return book

    _failed_at.pop(book.id, None)
    if description is not None:
        book.description = description
    if bio is not None:
        book.author_bio = bio
    if url is not None and book.wiki_url is None:
        book.wiki_url = url
    book.info_fetched_at = now
    await session.commit()
    return book
