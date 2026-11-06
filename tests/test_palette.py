import re
from pathlib import Path

from app.services.palette import PALETTE, color_for
from tests.conftest import read_chunk, signup
from tests.test_api import upstream
from tests.test_races import csrf

JS = Path(__file__).resolve().parents[1] / "app" / "static" / "palette.js"


def test_js_palette_matches_python():
    """리더 칩(palette.js)과 서버(palette.py)가 같은 사람에게 같은 색을 줘야 한다."""
    js = JS.read_text(encoding="utf-8")
    body = js[js.index("const PALETTE") : js.index("];")]
    assert tuple(re.findall(r"'(#[0-9A-Fa-f]{6})'", body)) == PALETTE
    assert "% PALETTE.length" in js and "root.colorFor = colorFor" in js


def test_color_for_is_deterministic_and_distinct_for_a_full_room():
    assert color_for(5) == color_for(5) == PALETTE[5 % len(PALETTE)]
    assert len({color_for(i) for i in range(1, 9)}) == 8  # 연달아 가입한 정원 8명은 모두 다른 색
    assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in PALETTE)


async def test_race_page_colors_track_and_board_alike(api, clock):
    async with api(upstream) as host, api(upstream) as friend:
        await signup(host, email="host@example.com", nickname="호스트")
        await signup(friend, email="friend@example.com", nickname="친구")
        page = await host.get("/races")
        race_url = (
            await host.post("/races/start/wikisource/긴글", data={"csrf": csrf(page.text), "days": "3"})
        ).headers["location"]
        race = (await host.get(race_url)).text
        code = re.search(r'id="code">([A-Z0-9]{6})<', race).group(1)
        preview = await friend.get(f"/join/{code}")
        await friend.post(f"/join/{code}", data={"csrf": csrf(preview.text)})
        book_id = re.search(r'href="/books/(\d+)"', race).group(1)
        token = (await friend.get(f"/books/{book_id}")).text.split('data-csrf="')[1].split('"')[0]
        await read_chunk(friend, book_id, 0, token, clock)
        html = (await host.get(race_url)).text
        total = int(re.search(r'data-total="(\d+)"', html).group(1))

    assert "/static/race.css" in html and "/static/palette.js" in html
    lanes = re.findall(
        r'class="rc-lane([^"]*)"[^>]*data-uid="(\d+)" style="--c:(#[0-9A-F]{6});--p:(\d+)"', html
    )
    rows = re.findall(r'<li class="[^"]*" data-uid="(\d+)" style="--c:(#[0-9A-F]{6})"', html)
    assert [(u, c) for _, u, c, _ in lanes] == rows  # 트랙과 순위가 같은 순서 · 같은 색
    assert all(c == color_for(int(u)) for u, c in rows)
    assert len({c for _, c in rows}) == 2
    leader, second = lanes
    assert "lead" in leader[0] and "lead" not in second[0]  # 1위(친구)에게만 왕관
    assert "me" in second[0]  # 호스트 화면이니 2등 레인이 '나'
    assert f"{total - 1}쪽 남음" in html and f"{total}쪽 남음" in html
    assert 'class="js-left"' in html and "종료까지" in html  # 남은 시간
