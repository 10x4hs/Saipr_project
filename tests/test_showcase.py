"""첫 화면 유명한 책 띠(app/data/showcase.json)."""

import json
from pathlib import Path

from app.web import CATALOG_INDEX, SHOWCASE
from tests.test_api import upstream

APP = Path(__file__).resolve().parent.parent / "app"
RAW = json.loads((APP / "data" / "showcase.json").read_text())


def test_showcase_json_is_valid_and_every_cover_exists():
    assert 12 <= len(RAW) <= 24
    titles = [b["title"] for b in RAW]
    assert len(set(titles)) == len(titles)
    for b in RAW:
        assert b["title"] and b["author"] and isinstance(b["publisher"], str)
        assert b["cover_src"].startswith("https://image.aladin.co.kr/product/") and "/cover500/" in b["cover_src"]
        assert b["cover"].startswith("/static/covers/showcase/") and b["cover"].endswith(".jpg")
        assert (APP / b["cover"].removeprefix("/")).is_file(), b["cover"]
        assert isinstance(b["readable"], bool)
        if b["readable"]:
            assert (b["source"], b["id"]) in CATALOG_INDEX, b["title"]
        else:
            assert "source" not in b and "id" not in b
    total = sum(f.stat().st_size for f in (APP / "static" / "covers" / "showcase").glob("*.jpg"))
    assert total < 1_500_000
    assert {"데미안", "채식주의자", "소년이 온다", "작별하지 않는다", "흰"} <= set(titles)
    assert [b["readable"] for b in SHOWCASE] == [b["readable"] for b in RAW]


async def test_landing_strip_links_readable_books_and_locks_the_rest(api):
    async with api(upstream) as c:
        landing = await c.get("/")
    html = landing.text
    assert landing.status_code == 200
    assert "/static/covers/showcase/demian.jpg" in html and "/static/landing-books.css" in html
    assert 'href="/open/wikisource/%EC%9A%B4%EC%88%98%20%EC%A2%8B%EC%9D%80%20%EB%82%A0"' in html
    locked = sum(not b["readable"] for b in RAW)
    assert html.count("data-locked title=") == locked * 2  # 끊김 없는 띠를 위해 두 벌
    assert "아직 해독에서 읽을 수 없는 책이에요" in html
