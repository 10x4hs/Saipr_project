"""카탈로그 책의 실제 표지 이미지를 받아 app/static/covers/에 저장하고 catalog.json에 경로를 적는다.

- 한국 작품: 알라딘 도서 검색 결과의 첫 표지 (제목 + 저자로 검색)
- 영어 고전: Open Library 검색의 cover_i

출시하지 않는 프로토타입 전용이다. 받은 이미지는 git에 올리지 않는다(.gitignore).
실행: python scripts/fetch_covers.py [--verify]   (이미 받은 표지는 건너뛴다. --verify는 다시 검사)
"""

import asyncio
import hashlib
import html
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "app" / "data" / "catalog.json"
COVERS = ROOT / "app" / "static" / "covers"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"}
ALADIN = "https://www.aladin.co.kr/search/wsearchresult.aspx"
_ALADIN_IMG = re.compile(r"https://image\.aladin\.co\.kr/product/\d+/\d+/cover\d*/[A-Za-z0-9_]+\.(?:jpg|png)")
CONCURRENCY = 4
VERIFY = "--verify" in sys.argv  # 이미 받은 한국어 표지도 제목 일치를 다시 확인


def file_for(book: dict) -> Path:
    key = hashlib.sha1(f"{book['source']}:{book['id']}".encode()).hexdigest()[:16]
    return COVERS / f"{key}.jpg"


_BOX = re.compile(r'<div class="ss_book_box" itemId="\d+">(.*?)(?=<div class="ss_book_box"|$)', re.S)
_TITLE = re.compile(r'class="bo3">([^<]+)</a>')


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", html.unescape(s)).lower()


async def aladin_cover(client: httpx.AsyncClient, book: dict) -> str | None:
    """제목이 실제로 일치하는 검색 결과의 표지만 쓴다.

    작가 이름으로 검색하면 그 작가의 대표작 선집(예: 「빈처」 → 『운수 좋은 날』)이 먼저 나와
    엉뚱한 표지가 붙기 때문에, 결과 제목이 책 제목으로 시작할 때만 받아들인다.
    """
    query = f"{book['title']} {book['author'] or ''}".strip()
    page = (await client.get(ALADIN, params={"SearchTarget": "Book", "SearchWord": query})).text
    want = _norm(book["title"])
    for block in _BOX.findall(page):
        t = _TITLE.search(block)
        if not t or not _norm(t.group(1)).startswith(want):
            continue
        m = _ALADIN_IMG.search(block)
        # 검색 목록은 200px 썸네일 — 같은 경로의 500px 판으로 바꾼다
        return re.sub(r"/cover\d*/", "/cover500/", m.group(0)) if m else None
    return None


async def openlibrary_cover(client: httpx.AsyncClient, book: dict) -> str | None:
    params = {"title": book["title"], "limit": 1, "fields": "cover_i"}
    if book["author"]:
        params["author"] = book["author"]
    docs = (await client.get("https://openlibrary.org/search.json", params=params)).json().get("docs", [])
    cid = docs[0].get("cover_i") if docs else None
    return f"https://covers.openlibrary.org/b/id/{cid}-L.jpg" if cid else None


async def fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, book: dict) -> bool:
    path = file_for(book)
    if VERIFY and book["source"] == "wikisource":
        # 다시 검사: 제목이 맞지 않는 표지는 지운다
        async with sem:
            try:
                url = await aladin_cover(client, book)
            except httpx.HTTPError:
                return bool(book.get("cover"))
            finally:
                await asyncio.sleep(0.4)
        if url != book.get("cover_src"):
            path.unlink(missing_ok=True)
            book.pop("cover", None)
            book.pop("cover_src", None)
            if not url:
                return False
    if path.exists() and book.get("cover_src"):
        book["cover"] = f"/static/covers/{path.name}"
        return True
    async with sem:
        try:
            find = aladin_cover if book["source"] == "wikisource" else openlibrary_cover
            url = await find(client, book)
            if not url:
                return False
            book["cover_src"] = url  # 배포 환경(표지 파일이 없는 곳)에서는 원본 주소로 보여 준다
            if path.exists():
                book["cover"] = f"/static/covers/{path.name}"
                return True
            img = await client.get(url)
            if img.status_code != 200 or len(img.content) < 2000:  # 빈 이미지·자리표시자 제외
                return False
            path.write_bytes(img.content)
            book["cover"] = f"/static/covers/{path.name}"
            return True
        except httpx.HTTPError:
            return False
        finally:
            await asyncio.sleep(0.4)


async def main() -> None:
    COVERS.mkdir(parents=True, exist_ok=True)
    books = json.loads(CATALOG.read_text())
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers=UA, timeout=20, follow_redirects=True) as client:
        found = await asyncio.gather(*(fetch_one(client, sem, b) for b in books))
    CATALOG.write_text(json.dumps(books, ensure_ascii=False, indent=1) + "\n")
    print(f"표지 {sum(found)} / {len(books)}권")


if __name__ == "__main__":
    asyncio.run(main())
