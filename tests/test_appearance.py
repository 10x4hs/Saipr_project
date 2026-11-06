"""배경 밝기(톤)가 글자색을 정한다 — 밝은 테마 + 어두운 배경에서 검은 글자가 안 보이던 버그."""

import re
from pathlib import Path

from app.core import appearance
from tests.conftest import signup
from tests.test_api import upstream

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_every_background_has_a_known_tone():
    assert set(appearance.BG_TONE) == appearance.BG_IDS
    assert set(appearance.BG_TONE.values()) <= set(appearance.TONES)
    # '기본'만 테마 색 바탕이라 테마를 따르고, 나머지는 짙은 바탕이다
    assert appearance.tone_of("plain") == "auto"
    assert appearance.tone_of("stars") == "dark"
    assert appearance.tone_of("paper") == "dark"
    assert appearance.tone_of("없는-배경") == "auto"


def test_resolve_exposes_bg_tone_regardless_of_mode():
    for mode in appearance.MODES:
        look = appearance.resolve({"mode": mode, "bg": "nebula"})
        assert look["bg_tone"] == "dark"
    assert appearance.resolve(None)["bg_tone"] == "auto"
    assert appearance.resolve({"bg": "nope"})["bg_tone"] == "auto"


async def _set_look(c, **look) -> None:
    home = await c.get("/")
    token = re.search(r'<meta name="csrf" content="([^"]+)"', home.text).group(1)
    r = await c.put("/api/v1/me/settings", json=look, headers={"X-CSRF-Token": token})
    assert r.status_code == 200


async def test_html_carries_bg_tone_for_dark_background_in_light_mode(api):
    async with api(upstream) as c:
        await signup(c)
        await _set_look(c, mode="light", bg="stars", accent="mono")
        page = await c.get("/discover")
        await _set_look(c, mode="light", bg="plain")
        plain = await c.get("/discover")
    html = re.search(r"<html[^>]*>", page.text).group(0)
    assert 'data-theme="light"' in html and 'data-bg-tone="dark"' in html
    assert 'data-bg-tone="auto"' in re.search(r"<html[^>]*>", plain.text).group(0)
    assert 'class="ranklist"' in page.text


async def test_customize_swatches_carry_their_tone_for_live_preview(api):
    async with api(upstream) as c:
        await signup(c)
        me = await c.get("/me")
    assert 'data-bgpick="plain" data-tone="auto"' in me.text
    assert 'data-bgpick="aurora" data-tone="dark"' in me.text


def test_css_dark_tone_overrides_text_vars_and_mono_accent():
    css = (STATIC / "app.css").read_text()
    block = css[css.index('html:root[data-bg-tone="dark"]{') :]
    block = block[: block.index("}")]
    for var in ("--text:#fafafa", "--body:", "--dim:", "--accent-strong:var(--accent)"):
        assert var in block
    looks = (STATIC / "looks.css").read_text()
    # 밝은 테마의 '기본' 강조색(검정)은 어두운 배경에선 쓰지 않는다
    mono_rules = [ln for ln in looks.splitlines() if '[data-accent="mono"]{--accent:#0a0a0a' in ln]
    assert mono_rules and all('[data-bg-tone="light"]' in ln or ':not([data-bg-tone="dark"])' in ln for ln in mono_rules)


def test_home_helix_supports_pointer_drag():
    js = (STATIC / "helix.js").read_text()
    for needle in ("pointerdown", "pointermove", "pointerup", "pointercancel", "dragstart"):
        assert needle in js
    assert "touch-action:none" in (STATIC / "app.css").read_text()
