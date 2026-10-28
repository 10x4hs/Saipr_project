"""카탈로그 책의 실제 표지 이미지를 받아 app/static/covers/에 저장하고 catalog.json에 경로를 적는다.

- 한국 작품: 알라딘 도서 검색 결과의 첫 표지 (제목 + 저자로 검색)
- 영어 고전: Open Library 검색의 cover_i

출시하지 않는 프로토타입 전용이다. 받은 이미지는 git에 올리지 않는다(.gitignore).
실행: python scripts/fetch_covers.py   (이미 받은 표지는 건너뛴다)
"""

import asyncio
import hashlib
import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "app" / "data" / "catalog.json"
COVERS = ROOT / "app" / "static" / "covers"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"}
ALADIN = "https://www.aladin.co.kr/search/wsearchresult.aspx"
_ALADIN_IMG = re.compile(r"https://image\.aladin\.co\.kr/product/\d+/\d+/cover\d*/[A-Za-z0-9_]+\.(?:jpg|png)")
CONCURRENCY = 4


def file_for(book: dict) -> Path:
    key = hashlib.sha1(f"{book['source']}:{book['id']}".encode()).hexdigest()[:16]
    return COVERS / f"{key}.jpg"


async def aladin_cover(client: httpx.AsyncClient, book: dict) -> str | None:
    query = f"{book['title']} {book['author'] or ''}".strip()
    html = (await client.get(ALADIN, params={"SearchTarget": "Book", "SearchWord": query})).text
    m = _ALADIN_IMG.search(html)
    # 검색 목록은 200px 썸네일 — 같은 경로의 500px 판으로 바꾼다
    return re.sub(r"/cover\d*/", "/cover500/", m.group(0)) if m else None


async def openlibrary_cover(client: httpx.AsyncClient, book: dict) -> str | None:
    params = {"title": book["title"], "limit": 1, "fields": "cover_i"}
    if book["author"]:
        params["author"] = book["author"]
    docs = (await client.get("https://openlibrary.org/search.json", params=params)).json().get("docs", [])
    cid = docs[0].get("cover_i") if docs else None
    return f"https://covers.openlibrary.org/b/id/{cid}-L.jpg" if cid else None


async def fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, book: dict) -> bool:
    path = file_for(book)
    if path.exists():
        book["cover"] = f"/static/covers/{path.name}"
        return True
    async with sem:
        try:
            find = aladin_cover if book["source"] == "wikisource" else openlibrary_cover
            url = await find(client, book)
            if not url:
                return False
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
