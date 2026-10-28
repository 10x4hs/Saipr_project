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

GENRES = ["단편소설", "중편소설", "장편소설", "동화", "시집", "수필"]
MIN_BODY_CHARS = 800
LAST_PD_DEATH_YEAR = 1962

_AUTHOR = re.compile(r"\|\s*저자\s*=\s*\[\[(?:저자:)?[^|\]]*\|?([^\]]*)\]\]")
_YEAR = re.compile(r"분류:(\d{4})년 작품")
_DEATH = re.compile(r"분류:(\d{4})년 죽음")
_AUTHOR_PAGE = re.compile(r"\|\s*저자\s*=\s*\[\[(저자:[^|\]]+)")
_TEMPLATE = re.compile(r"\{\{.*?\}\}", re.S)
_LINK_LINE = re.compile(r"^\s*[*#:]*\s*\[\[[^\]]*\]\]\s*$", re.M)
_TOP_ITEM = re.compile(r'<li><a href="/ebooks/(\d+)">([^<]+?) by ([^<(]+?) \(\d+\)</a>')


async def wiki(client: httpx.AsyncClient, **params) -> dict:
    params |= {"action": "query", "format": "json", "formatversion": 2}
    r = await client.get(WIKI_API, params=params)
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
            if body_chars(src) < MIN_BODY_CHARS:
                continue
            if "분류:PD-old-70" not in cats:
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
        await asyncio.sleep(0.5)  # 위키미디어 서버 배려
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
    # 카테고리 수집에서 빠지는 유명작(분류가 덜 달린 문서)은 popular.json의 extra로 보탠다
    extra = json.loads((OUT.parent / "popular.json").read_text())["extra"]
    have = {(b["source"], b["id"]) for b in books}
    books = [e for e in extra if (e["source"], e["id"]) not in have] + books
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(books + top, ensure_ascii=False, indent=1) + "\n")
    print(f"→ {OUT} ({len(books) + len(top)}권)")


if __name__ == "__main__":
    asyncio.run(main())
