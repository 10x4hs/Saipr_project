"""책마다 소개 유튜브 영상(북튜버 리뷰·요약)을 모아 app/data/videos.json에 둔다.

YouTube 검색 결과 페이지에서 영상 id·제목·채널·길이·조회수만 읽는다(재생은 YouTube 임베드).
알려진 책 소개 채널(너진똑, 겨울서점 등)의 영상을 앞에 둔다.
실행: python scripts/build_videos.py [--rebuild]
"""

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parent.parent / "app" / "data"
OUT = DATA / "videos.json"
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "Accept-Language": "ko-KR",
}
PER_BOOK = 4

# 책 소개를 꾸준히 하는 채널 — 이 채널 영상을 먼저 보여 준다
BOOKTUBERS = [
    "너진똑", "겨울서점", "문학줍줍", "책과삶", "민음사TV", "지식인사이드", "체인지그라운드", "책그림",
    "1분 책", "책 읽어주는 남자", "북툰", "일당백", "사피엔스 스튜디오", "김미경", "열정에기름붓기",
    "CommbooksTV", "tvN STORY", "창비", "문학동네", "책추남", "북끄북끄", "책읽는 다락방",
]  # fmt: skip
MAX_MINUTES = 90
_DATA = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)


def _videos(node, out: list) -> None:
    if isinstance(node, dict):
        if "videoRenderer" in node:
            v = node["videoRenderer"]
            out.append(
                {
                    "id": v["videoId"],
                    "title": "".join(r.get("text", "") for r in v.get("title", {}).get("runs", [])),
                    "channel": (v.get("ownerText", {}).get("runs") or [{}])[0].get("text"),
                    "length": v.get("lengthText", {}).get("simpleText"),
                    "views": v.get("viewCountText", {}).get("simpleText"),
                }
            )
        for x in node.values():
            _videos(x, out)
    elif isinstance(node, list):
        for x in node:
            _videos(x, out)


def _norm(s: str) -> str:
    """띄어쓰기·문장부호를 지우고 소문자로 — 제목 비교용."""
    return re.sub(r"[\W_]+", "", s).lower()


def _minutes(length: str) -> float:
    parts = [int(p) for p in length.split(":")]
    total = 0
    for p in parts:
        total = total * 60 + p
    return total / 60


def _relevant(v: dict, title: str, author: str | None) -> bool:
    # 쇼츠·라이브(길이 없음)와 90분 넘는 영상(낭독·강의 통째) 제외
    if not v.get("length") or _minutes(v["length"]) > MAX_MINUTES:
        return False
    # 책 제목 전체가 영상 제목에 있어야 한다
    if _norm(title) not in _norm(v["title"]):
        return False
    # "흰"·"고래"·"모모"처럼 짧은 제목은 다른 영상과 겹치기 쉬워 작가 이름도 요구
    if len(_norm(title)) <= 2:
        names = (author or "").split(",")[0].split()
        if not names:
            return False
        # 전체 이름, 또는 성(외국 이름은 마지막 단어, 한국 이름은 첫 글자)
        keys = {_norm("".join(names)), _norm(names[-1]) if len(names) > 1 else _norm(names[0])[:1]}
        hay = _norm(v["title"] + (v.get("channel") or ""))
        return any(k and k in hay for k in keys)
    return True


def _rank(v: dict, title: str) -> tuple:
    channel = v.get("channel") or ""
    booktuber = next((i for i, c in enumerate(BOOKTUBERS) if c.lower() in channel.lower()), len(BOOKTUBERS))
    on_topic = title.replace(" ", "") in v["title"].replace(" ", "")
    return (not on_topic, booktuber)


async def search(client: httpx.AsyncClient, title: str, author: str | None) -> list[dict]:
    q = f"{title} {author or ''} 책 리뷰".strip()
    page = (await client.get("https://www.youtube.com/results", params={"search_query": q})).text
    m = _DATA.search(page)
    if not m:
        return []
    found: list[dict] = []
    _videos(json.loads(m.group(1)), found)
    # 관련 없는 영상은 빼고, 북튜버 우선
    found = [v for v in found if _relevant(v, title, author)]
    return sorted(found, key=lambda v: _rank(v, title))[:PER_BOOK]


async def main() -> None:
    store = json.loads((DATA / "store.json").read_text())
    catalog = {(b["source"], b["id"]): b for b in json.loads((DATA / "catalog.json").read_text())}
    popular = [
        catalog[tuple(k)]
        for k in json.loads((DATA / "popular.json").read_text())["order"]
        if tuple(k) in catalog
    ]
    jobs = [(f"store:{b['id']}", re.sub(r"\s*\(.*?\)|\s*\d+$", "", b["title"]), b["author"]) for b in store]
    jobs += [(f"{b['source']}:{b['id']}", b["title"], b["author"]) for b in popular]
    rebuild = "--rebuild" in sys.argv  # 캐시 무시하고 모두 다시 검색
    out = {} if rebuild or not OUT.exists() else json.loads(OUT.read_text())
    async with httpx.AsyncClient(headers=UA, timeout=25, follow_redirects=True) as client:
        for key, title, author in jobs:
            if out.get(key):
                continue
            try:
                out[key] = await search(client, title, author)
            except (httpx.HTTPError, json.JSONDecodeError):
                continue
            print(len(out[key]), title)
            await asyncio.sleep(0.8)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"→ {OUT} ({sum(1 for v in out.values() if v)}권에 영상)")


if __name__ == "__main__":
    asyncio.run(main())
