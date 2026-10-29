"""저작권이 살아 있는 유명 도서의 정보·표지·알라딘 전자책 링크를 모아 app/data/store.json에 둔다.

본문은 없다. 앱은 표지와 정보를 보여 주고, 사는 곳(알라딘 전자책 상품 페이지)으로 연결한다.
실행: python scripts/build_store.py
"""

import asyncio
import html as htmllib
import json
import re
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "store.json"
SEARCH = "https://www.aladin.co.kr/search/wsearchresult.aspx"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"}

# (검색어, 제목에 꼭 들어갈 말) — 많이 읽히는 순서대로
FAMOUS = [
    ("데미안 헤르만 헤세", "데미안"),
    ("동물농장 조지 오웰", "동물농장"),
    ("1984 조지 오웰", "1984"),
    ("어린 왕자 생텍쥐페리", "어린 왕자"),
    ("노인과 바다 헤밍웨이", "노인과 바다"),
    ("호밀밭의 파수꾼", "호밀밭의 파수꾼"),
    ("연금술사 파울로 코엘료", "연금술사"),
    ("채식주의자 한강", "채식주의자"),
    ("소년이 온다 한강", "소년이 온다"),
    ("작별하지 않는다 한강", "작별하지 않는다"),
    ("빨강의 자서전", "빨강의 자서전"),
    ("아몬드 손원평", "아몬드"),
    ("불편한 편의점 김호연", "불편한 편의점"),
    ("달러구트 꿈 백화점", "달러구트 꿈 백화점"),
    ("미드나잇 라이브러리", "미드나잇 라이브러리"),
    ("나미야 잡화점의 기적", "나미야 잡화점의 기적"),
    ("82년생 김지영", "82년생 김지영"),
    ("파친코 이민진", "파친코"),
    ("사피엔스 유발 하라리", "사피엔스"),
    ("총 균 쇠 재레드 다이아몬드", "총 균 쇠"),
    ("코스모스 칼 세이건", "코스모스"),
    ("이방인 알베르 카뮈", "이방인"),
    ("페스트 알베르 카뮈", "페스트"),
    ("인간 실격 다자이 오사무", "인간 실격"),
    ("상실의 시대 무라카미 하루키", "상실의 시대"),
    ("해변의 카프카 무라카미 하루키", "해변의 카프카"),
    ("멋진 신세계 올더스 헉슬리", "멋진 신세계"),
    ("앵무새 죽이기 하퍼 리", "앵무새 죽이기"),
    ("향수 파트리크 쥐스킨트", "향수"),
    ("나의 라임 오렌지나무", "나의 라임 오렌지나무"),
    ("모모 미하엘 엔데", "모모"),
    ("칼의 노래 김훈", "칼의 노래"),
    ("난장이가 쏘아올린 작은 공", "난장이가 쏘아올린 작은 공"),
    ("무진기행 김승옥", "무진기행"),
    ("토지 박경리", "토지"),
    ("82년생", "82년생"),
    ("역행자 자청", "역행자"),
    ("세이노의 가르침", "세이노의 가르침"),
    ("물고기는 존재하지 않는다", "물고기는 존재하지 않는다"),
]

_BOX = re.compile(r'<div class="ss_book_box" itemId="(\d+)">(.*?)(?=<div class="ss_book_box"|$)', re.S)
_COVER = re.compile(r'<img src="(https://image\.aladin\.co\.kr/product/[^"]+?/cover\d*/[^"]+?\.(?:jpg|png))"')
_TITLE = re.compile(r'class="bo3">([^<]+)</a>')
_AUTHOR = re.compile(r'AuthorSearch=[^"]+">([^<]+)</a>')
_PRICE = re.compile(r'<span class="ss_p2"><em>([\d,]+)</em>원')


def _clean(s: str) -> str:
    return htmllib.unescape(re.sub(r"\s+", " ", s)).strip()


async def find(client: httpx.AsyncClient, query: str, must: str) -> dict | None:
    page = (await client.get(SEARCH, params={"SearchTarget": "eBook", "SearchWord": query})).text
    for item_id, block in _BOX.findall(page):
        t = _TITLE.search(block)
        if not t or not _clean(t.group(1)).startswith(must):  # 해설서·연구서 제외
            continue
        cover = _COVER.search(block)
        author = _AUTHOR.search(block)
        price = _PRICE.search(block)
        return {
            "id": item_id,
            "title": _clean(t.group(1)),
            "author": _clean(author.group(1)) if author else None,
            "cover": re.sub(r"/cover\d*/", "/cover500/", cover.group(1)) if cover else None,
            "price": int(price.group(1).replace(",", "")) if price else None,
            "url": f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}&start=pebook",
        }
    return None


async def main() -> None:
    out, seen = [], set()
    async with httpx.AsyncClient(headers=UA, timeout=20, follow_redirects=True) as client:
        for query, must in FAMOUS:
            try:
                book = await find(client, query, must)
            except httpx.HTTPError:
                book = None
            if book and book["id"] not in seen:
                seen.add(book["id"])
                out.append(book)
            print(("✓" if book else "✗"), query, "→", book["title"] if book else "")
            await asyncio.sleep(0.6)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"→ {OUT} ({len(out)}권)")


if __name__ == "__main__":
    asyncio.run(main())
