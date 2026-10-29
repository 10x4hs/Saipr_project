"""서가 카탈로그(app/data/catalog.json)를 만든다.

- 위키문헌: 장르 분류에 속하면서 저자 사망 연도로 퍼블릭 도메인이 확인되는 문서만.
  한국은 2013년 보호기간이 사후 50→70년으로 늘었지만 1962년 이전 사망 저자의 작품은
  이미 만료되어 계속 퍼블릭 도메인이다. 그래서 `PD-old-70`은 그대로, `PD-old-50`은
  저자 문서의 `NNNN년 죽음` 분류로 1962년 이전 사망이 확인될 때만 넣는다.
  본문 없이 하위 문서 목록만 있는 문서(장편 목차 등)와 번역 문서는 뺀다.
- 구텐베르크: 최근 인기 상위 100권.

실행: python scripts/build_catalog.py
"""

import asyncio
import json
import re
from pathlib import Path

import httpx

WIKI_API = "https://ko.wikisource.org/w/api.php"
GUTENBERG_TOP = "https://www.gutenberg.org/browse/scores/top"
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "catalog.json"
UA = {"User-Agent": "saipr-catalog/0.1 (+https://github.com/hsK10x2/Saipr_project)"}

GENRES = [
    "단편소설",
    "중편소설",
    "장편소설",
    "고전소설",
    "신소설",
    "동화",
    "시",
    "시집",
    "희곡",
    "판소리",
    "수필",
]
# 구텐베르크 장르 검색어 → 서가 이름 (다운로드 많은 순 50권씩)
WORLD = {
    "detective fiction": "세계 · 추리",
    "science fiction": "세계 · SF",
    "fairy tales": "세계 · 동화",
    "adventure stories": "세계 · 모험",
    "horror tales": "세계 · 공포",
    "love stories": "세계 · 로맨스",
    "poetry": "세계 · 시",
    "drama": "세계 · 희곡",
    "philosophy": "세계 · 철학",
    "children's literature": "세계 · 어린이",
    "history": "세계 · 역사",
}
GUTENBERG_SEARCH = "https://www.gutenberg.org/ebooks/search/"
_BOOKLINK = re.compile(
    r'<li class="booklink">.*?href="/ebooks/(\d+)".*?<span class="title">([^<]+)</span>'
    r'(?:\s*<span class="subtitle">([^<]+)</span>)?',
    re.S,
)
MIN_BODY_CHARS = 800
MIN_POEM_CHARS = 120  # 시는 짧다
# 조선 시대 고전소설·판소리는 작자 미상의 수백 년 된 작품이라 그 자체로 퍼블릭 도메인
ANCIENT_GENRES = {"고전소설", "판소리"}
PD_TAGS = {"분류:PD-old-70", "분류:PD-old-100", "분류:PD-old"}
LAST_PD_DEATH_YEAR = 1962

_AUTHOR = re.compile(r"\|\s*저자\s*=\s*\[\[(?:저자:)?[^|\]]*\|?([^\]]*)\]\]")
_YEAR = re.compile(r"분류:(\d{4})년 작품")
_DEATH = re.compile(r"분류:(\d{4})년 죽음")
_AUTHOR_PAGE = re.compile(r"\|\s*저자\s*=\s*\[\[(저자:[^|\]]+)")
_TEMPLATE = re.compile(r"\{\{.*?\}\}", re.S)
_LINK_LINE = re.compile(r"^\s*[*#:]*\s*\[\[[^\]]*\]\]\s*$", re.M)
_TOP_ITEM = re.compile(r'<li><a href="/ebooks/(\d+)">([^<]+?) by ([^<(]+?) \(\d+\)</a>')


async def wiki(client: httpx.AsyncClient, **params) -> dict:
    """위키미디어 API — 너무 빨리 부르면 빈 응답이 오므로 쉬었다가 다시 시도한다."""
    params |= {"action": "query", "format": "json", "formatversion": 2}
    for attempt in range(5):
        r = await client.get(WIKI_API, params=params)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        await asyncio.sleep(2 + attempt * 3)
    r.raise_for_status()
    return r.json()


async def members(client: httpx.AsyncClient, genre: str) -> list[str]:
    titles, cont = [], {}
    while True:
        d = await wiki(
            client, list="categorymembers", cmtitle=f"분류:{genre}", cmnamespace=0, cmlimit=500, **cont
        )
        titles += [m["title"] for m in d["query"]["categorymembers"]]
        if "continue" not in d:
            return titles
        cont = {"cmcontinue": d["continue"]["cmcontinue"]}


def body_chars(wikitext: str) -> int:
    text = _LINK_LINE.sub("", _TEMPLATE.sub("", wikitext))
    return len(re.sub(r"\s+", "", text))


_deaths: dict[str, int | None] = {}


async def death_year(client: httpx.AsyncClient, author_page: str) -> int | None:
    if author_page not in _deaths:
        d = await wiki(client, titles=author_page, prop="categories", cllimit="max", redirects=1)
        cats = [c["title"] for p in d["query"]["pages"] for c in p.get("categories", [])]
        _deaths[author_page] = next((int(m.group(1)) for c in cats if (m := _DEATH.search(c))), None)
    return _deaths[author_page]


async def describe(client: httpx.AsyncClient, titles: list[str], genre: str) -> list[dict]:
    out = []
    for i in range(0, len(titles), 25):
        d = await wiki(
            client,
            titles="|".join(titles[i : i + 25]),
            prop="categories|revisions",
            cllimit="max",
            rvprop="content",
            rvslots="main",
        )
        for p in d["query"]["pages"]:
            cats = [c["title"] for c in p.get("categories", [])]
            if "revisions" not in p:
                continue
            src = p["revisions"][0]["slots"]["main"]["content"]
            if body_chars(src) < (MIN_POEM_CHARS if genre in ("시", "시집") else MIN_BODY_CHARS):
                continue
            if genre not in ANCIENT_GENRES and not PD_TAGS & set(cats):
                page = m.group(1).strip() if (m := _AUTHOR_PAGE.search(src)) else None
                died = await death_year(client, page) if page else None
                if "분류:PD-old-50" not in cats or died is None or died > LAST_PD_DEATH_YEAR:
                    continue
            year = next((int(m.group(1)) for c in cats if (m := _YEAR.search(c))), None)
            author = m.group(1).strip() if (m := _AUTHOR.search(src)) else None
            out.append(
                {
                    "source": "wikisource",
                    "id": p["title"],
                    "title": re.sub(r"\s*\([^)]*\)$", "", p["title"]),
                    "author": author or None,
                    "year": year,
                    "genre": genre,
                    "lang": "ko",
                }
            )
        await asyncio.sleep(1.0)  # 위키미디어 서버 배려
    return out


async def gutenberg(client: httpx.AsyncClient) -> list[dict]:
    html = (await client.get(GUTENBERG_TOP)).text
    seen, out = set(), []
    for gid, title, author in _TOP_ITEM.findall(html):
        if gid in seen:
            continue
        seen.add(gid)
        out.append(
            {
                "source": "gutendex",
                "id": gid,
                "title": title.strip(),
                "author": author.strip(),
                "year": None,
                "genre": "세계 고전",
                "lang": None,
            }
        )
    return out[:100]


async def gutenberg_genre(client: httpx.AsyncClient, query: str, shelf: str, pages: int = 2) -> list[dict]:
    out = []
    for page in range(pages):
        html = (
            await client.get(
                GUTENBERG_SEARCH,
                params={"query": query, "sort_order": "downloads", "start_index": 1 + page * 25},
            )
        ).text
        for gid, title, author in _BOOKLINK.findall(html):
            out.append(
                {
                    "source": "gutendex",
                    "id": gid,
                    "title": title.strip(),
                    "author": (author or "").strip() or None,
                    "year": None,
                    "genre": shelf,
                    "lang": None,
                }
            )
        await asyncio.sleep(1.0)
    return out


async def main() -> None:
    async with httpx.AsyncClient(headers=UA, timeout=30, follow_redirects=True) as client:
        books, seen = [], set()
        for genre in GENRES:
            titles = [t for t in await members(client, genre) if not t.startswith("번역:") and "/" not in t]
            for b in await describe(client, titles, genre):
                if b["id"] not in seen:
                    seen.add(b["id"])
                    books.append(b)
            print(f"{genre}: {sum(b['genre'] == genre for b in books)}")
        top = await gutenberg(client)
        print(f"세계 고전: {len(top)}")
        seen_g = {b["id"] for b in top}
        for query, shelf in WORLD.items():
            got = [b for b in await gutenberg_genre(client, query, shelf) if b["id"] not in seen_g]
            seen_g |= {b["id"] for b in got}
            top += got
            print(f"{shelf}: {len(got)}")
    # 카테고리 수집에서 빠지는 유명작(분류가 덜 달린 문서)은 popular.json의 extra로 보탠다
    extra = json.loads((OUT.parent / "popular.json").read_text())["extra"]
    have = {(b["source"], b["id"]) for b in books}
    books = [e for e in extra if (e["source"], e["id"]) not in have] + books
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(books + top, ensure_ascii=False, indent=1) + "\n")
    print(f"→ {OUT} ({len(books) + len(top)}권)")


if __name__ == "__main__":
    asyncio.run(main())
