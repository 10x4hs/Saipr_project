"""디자인 시스템 — Glass(처음 시안) · Material 3 · Cupertino(iOS), 각각 라이트/다크.

화면 코드는 여기 있는 위젯 팩토리(card, button, field, nav …)만 쓴다. 설정에서 디자인을 바꾸면
같은 화면이 다른 재질로 다시 그려진다. 색·간격·모서리 값은 디자인마다 한곳(Palette)에 모았다.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

GLASS, MATERIAL, CUPERTINO = "glass", "material", "cupertino"
DESIGNS = {GLASS: "글래스", MATERIAL: "머티리얼", CUPERTINO: "iOS"}

# 글꼴: Flet은 글꼴 파일 하나를 한 이름으로 등록하므로 굵기마다 이름을 따로 둔다
FONTS = {
    "Pretendard": "fonts/Pretendard-Regular.ttf",
    "Pretendard Medium": "fonts/Pretendard-Medium.ttf",
    "Pretendard SemiBold": "fonts/Pretendard-SemiBold.ttf",
    "Pretendard Bold": "fonts/Pretendard-Bold.ttf",
    "Gowun Batang": "fonts/GowunBatang-Regular.ttf",
    "Gowun Batang Bold": "fonts/GowunBatang-Bold.ttf",
}
WEIGHT_FONT = {"regular": "Pretendard", "medium": "Pretendard Medium", "semibold": "Pretendard SemiBold", "bold": "Pretendard Bold"}

AVATAR_COLORS = ("#3b82f6", "#22a06b", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6", "#ec4899", "#64748b")
COVER_COLORS = ("#8e6c4a", "#b5523b", "#3a5a8c", "#2f6b4f", "#6b4f8e", "#8c3a5a", "#4a7a8c", "#7a6a3a")
HIGHLIGHT_COLORS = {"yellow": "#FFD95A", "green": "#9BE3A5", "blue": "#9CC9FF", "pink": "#FFADC8"}

SPRING = ft.AnimationCurve.EASE_OUT_BACK
SMOOTH = ft.AnimationCurve.EASE_OUT_CUBIC


def alpha(color: str, a: float) -> str:
    return ft.Colors.with_opacity(a, color)


def avatar_color(uid: int | None, given: str | None = None) -> str:
    return given or AVATAR_COLORS[(uid or 0) % len(AVATAR_COLORS)]


def cover_color(key: object, given: str | None = None) -> str:
    return given or COVER_COLORS[zlib.crc32(str(key).encode()) % len(COVER_COLORS)]


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str  # 카드 바탕(유리는 반투명 흰색)
    fg: str
    muted: str
    accent: str
    on_accent: str
    divider: str
    danger: str
    radius: int
    card_radius: int
    seed: str


PALETTES: dict[tuple[str, bool], Palette] = {
    (GLASS, False): Palette("#9ea3a9", alpha("#ffffff", 0.16), "#ffffff", alpha("#ffffff", 0.78), "#ffffff", "#1d1d1f", alpha("#ffffff", 0.22), "#ffb4ab", 9999, 28, "#6f767f"),
    (GLASS, True): Palette("#1b2336", alpha("#ffffff", 0.09), "#ffffff", alpha("#ffffff", 0.72), "#ffffff", "#0b1020", alpha("#ffffff", 0.16), "#ffb4ab", 9999, 28, "#1b2336"),
    (MATERIAL, False): Palette("#fbf8fd", "#f0edf4", "#1b1b1f", "#5d5e66", "#4a5ba8", "#ffffff", "#e3e1ec", "#ba1a1a", 20, 20, "#4a5ba8"),
    (MATERIAL, True): Palette("#131318", "#1f1f25", "#e4e1e9", "#c6c5d0", "#b7c4ff", "#1e2d6e", "#2f2f36", "#ffb4ab", 20, 20, "#4a5ba8"),
    (CUPERTINO, False): Palette("#f2f2f7", "#ffffff", "#000000", "#6c6c70", "#007aff", "#ffffff", "#e5e5ea", "#ff3b30", 12, 14, "#007aff"),
    (CUPERTINO, True): Palette("#000000", "#1c1c1e", "#ffffff", "#98989f", "#0a84ff", "#ffffff", "#38383a", "#ff453a", 12, 14, "#0a84ff"),
}


class Design:
    """현재 디자인. app.design으로 어디서나 꺼내 쓴다."""

    def __init__(self, name: str = GLASS, dark: bool = False) -> None:
        self.name = name if name in DESIGNS else GLASS
        self.dark = dark
        self.p = PALETTES[(self.name, self.dark)]

    # ── 페이지 설정 ───────────────────────────────────
    def apply(self, page: ft.Page) -> None:
        page.fonts = FONTS
        brightness = ft.Brightness.DARK if self.dark else ft.Brightness.LIGHT
        # iOS처럼 밀어서 뒤로가기(Cupertino 전환)를 글래스·iOS에서 모든 플랫폼에 쓴다
        slide = ft.PageTransitionTheme.CUPERTINO
        transitions = ft.PageTransitionsTheme(
            android=ft.PageTransitionTheme.PREDICTIVE if self.name == MATERIAL else slide,
            ios=slide, macos=slide, linux=slide, windows=slide,
        )
        theme = ft.Theme(
            color_scheme_seed=self.p.seed,
            font_family="Pretendard",
            use_material3=True,
            page_transitions=transitions,
            scaffold_bgcolor=self.p.bg,
            color_scheme=ft.ColorScheme(primary=self.p.accent if self.name != GLASS else "#1d1d1f",
                                        surface=self.p.bg if self.name != GLASS else "#ffffff"),
        )
        page.theme = page.dark_theme = theme
        page.theme_mode = ft.ThemeMode.DARK if self.dark else ft.ThemeMode.LIGHT
        page.bgcolor = self.p.bg
        _ = brightness

    @property
    def is_glass(self) -> bool:
        return self.name == GLASS

    # ── 글자 ────────────────────────────────────────
    def text(self, value: str, size: float = 15, weight: str = "regular", color: str | None = None,
             muted: bool = False, max_lines: int | None = None, align: ft.TextAlign | None = None,
             serif: bool = False, selectable: bool = False, height: float | None = None, **kw) -> ft.Text:
        family = ("Gowun Batang Bold" if weight in ("bold", "semibold") else "Gowun Batang") if serif else WEIGHT_FONT[weight]
        style = ft.TextStyle(height=height, letter_spacing=-0.3 if size >= 20 else -0.1) if (height or size >= 20) else None
        return ft.Text(value, size=size, font_family=family, color=color or (self.p.muted if muted else self.p.fg),
                       max_lines=max_lines, overflow=ft.TextOverflow.ELLIPSIS if max_lines else None,
                       text_align=align, selectable=selectable, style=style, **kw)

    def title(self, value: str, size: float = 32) -> ft.Text:
        return self.text(value, size=size, weight="bold", height=1.15)

    def caption(self, value: str, size: float = 13, **kw) -> ft.Text:
        return self.text(value, size=size, muted=True, **kw)

    # ── 표면 ────────────────────────────────────────
    def card(self, content: ft.Control, padding: float | ft.Padding = 20, on_click: Callable | None = None,
             radius: int | None = None, strong: bool = False, key: str | None = None, **kw) -> ft.Container:
        r = radius if radius is not None else self.p.card_radius
        if self.is_glass:
            box = ft.Container(
                content=content, padding=padding, border_radius=r, blur=ft.Blur(30, 30),
                bgcolor=alpha("#ffffff", 0.92 if strong else (0.12 if self.dark else 0.16)),
                border=ft.Border.all(1, alpha("#ffffff", 0.38)),
                shadow=ft.BoxShadow(blur_radius=40, offset=ft.Offset(0, 18), color=alpha("#000000", 0.14)),
                gradient=None if strong else ft.LinearGradient(
                    begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
                    colors=[alpha("#ffffff", 0.14), alpha("#ffffff", 0.0)]),
                **kw,
            )
        elif self.name == MATERIAL:
            box = ft.Container(content=content, padding=padding, border_radius=r,
                               bgcolor=self.p.accent if strong else self.p.surface, **kw)
        else:
            box = ft.Container(content=content, padding=padding, border_radius=r,
                               bgcolor=self.p.surface, **kw)
        if key:
            box.key = key
        if on_click:
            pressable(box, on_click)
            box.ink = not self.is_glass
        return box

    def section(self, title: str, action: str | None = None, on_action: Callable | None = None) -> ft.Row:
        items: list[ft.Control] = [self.text(title, 19, "bold")]
        if action:
            items.append(ft.TextButton(content=self.text(action, 13, "medium", muted=not on_action, color=None if self.is_glass else self.p.accent), on_click=on_action))
        return ft.Row(items, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    # ── 버튼 ────────────────────────────────────────
    def button(self, label: str, on_click: Callable | None = None, icon: str | None = None, kind: str = "primary",
               expand: bool = False, disabled: bool = False, key: str | None = None) -> ft.Control:
        p = self.p
        if kind == "primary":
            bg, fg = (alpha("#ffffff", 0.92), "#1d1d1f") if self.is_glass else (p.accent, p.on_accent)
        elif kind == "secondary":
            bg, fg = (alpha("#ffffff", 0.18), "#ffffff") if self.is_glass else (alpha(p.accent, 0.12), p.accent)
        elif kind == "danger":
            bg, fg = (alpha("#ff3b30", 0.85), "#ffffff")
        else:  # text
            bg, fg = ("transparent", p.fg if self.is_glass else p.accent)
        shape = ft.RoundedRectangleBorder(radius=p.radius if self.name != CUPERTINO else 12)
        content = ft.Row([*( [ft.Icon(icon, size=18, color=fg)] if icon else []), self.text(label, 15, "semibold", color=fg)],
                         spacing=8, tight=True, alignment=ft.MainAxisAlignment.CENTER)
        btn = ft.Button(
            content=content, on_click=on_click, disabled=disabled, expand=expand,
            style=ft.ButtonStyle(bgcolor=bg, color=fg, shape=shape, elevation=0,
                                 padding=ft.Padding.symmetric(horizontal=22, vertical=14),
                                 overlay_color=alpha(fg, 0.08)),
        )
        if key:
            btn.key = key
        return btn

    def icon_button(self, icon: str, on_click: Callable | None = None, tooltip: str | None = None,
                    color: str | None = None, selected: bool = False, key: str | None = None) -> ft.IconButton:
        b = ft.IconButton(icon=icon, on_click=on_click, tooltip=tooltip, icon_color=color or self.p.fg,
                          bgcolor=alpha(self.p.fg, 0.12) if selected else None)
        if key:
            b.key = key
        return b

    def chip(self, label: str, selected: bool = False, on_click: Callable | None = None, icon: str | None = None) -> ft.Container:
        p = self.p
        if self.is_glass:
            bg, fg, border = (alpha("#ffffff", 0.92), "#1d1d1f", None) if selected else (alpha("#ffffff", 0.12), "#ffffff", ft.Border.all(1, alpha("#ffffff", 0.35)))
        else:
            bg, fg, border = (p.accent, p.on_accent, None) if selected else (p.surface, p.fg, ft.Border.all(1, p.divider))
        return ft.Container(
            content=ft.Row([*( [ft.Icon(icon, size=15, color=fg)] if icon else []), self.text(label, 13, "medium", color=fg)], spacing=6, tight=True),
            padding=ft.Padding.symmetric(horizontal=14, vertical=8), border_radius=9999, bgcolor=bg, border=border,
            on_click=on_click, animate=ft.Animation(200, SMOOTH),
        )

    def segmented(self, options: list[tuple[str, str]], selected: str, on_change: Callable[[str], None]) -> ft.Control:
        if self.name == CUPERTINO:
            idx = next((i for i, (k, _) in enumerate(options) if k == selected), 0)
            return ft.CupertinoSlidingSegmentedButton(
                controls=[self.text(lbl, 13, "medium") for _, lbl in options], selected_index=idx,
                on_change=lambda e: on_change(options[int(e.control.selected_index)][0]),
            )
        return ft.Row([self.chip(lbl, k == selected, on_click=lambda e, k=k: on_change(k)) for k, lbl in options],
                      spacing=8, scroll=ft.ScrollMode.HIDDEN)

    def field(self, label: str, value: str = "", hint: str | None = None, password: bool = False,
              keyboard: ft.KeyboardType | None = None, on_submit: Callable | None = None, on_change: Callable | None = None,
              multiline: bool = False, max_length: int | None = None, autofocus: bool = False,
              icon: str | None = None, key: str | None = None) -> ft.TextField:
        p = self.p
        glass = self.is_glass
        tf = ft.TextField(
            label=label or None, value=value, hint_text=hint, password=password, can_reveal_password=password,
            keyboard_type=keyboard, on_submit=on_submit, on_change=on_change, multiline=multiline,
            min_lines=1, max_lines=4 if multiline else 1, max_length=max_length, autofocus=autofocus,
            prefix_icon=icon, border_radius=16 if not glass else 9999,
            filled=True, fill_color=alpha("#ffffff", 0.22) if glass else (p.surface if self.name == CUPERTINO else alpha(p.fg, 0.05)),
            border_color="transparent", focused_border_color=alpha("#ffffff", 0.7) if glass else p.accent,
            color=p.fg, cursor_color=p.fg if glass else p.accent,
            label_style=ft.TextStyle(color=p.muted, font_family="Pretendard"),
            hint_style=ft.TextStyle(color=alpha(p.fg, 0.5), font_family="Pretendard"),
            text_style=ft.TextStyle(font_family="Pretendard", size=16),
            content_padding=ft.Padding.symmetric(horizontal=20, vertical=14),
        )
        if key:
            tf.key = key
        return tf

    def switch(self, value: bool, on_change: Callable) -> ft.Control:
        if self.name == CUPERTINO:
            return ft.CupertinoSwitch(value=value, on_change=on_change)
        return ft.Switch(value=value, on_change=on_change, active_color=self.p.accent if not self.is_glass else "#34c759")

    def progress(self, value: float, height: int = 5, soft: bool = False) -> ft.Control:
        p = self.p
        color = ("#bfe0ff" if soft else "#ffffff") if self.is_glass else p.accent
        track = alpha("#ffffff", 0.25) if self.is_glass else alpha(p.fg, 0.1)
        return ft.ProgressBar(value=max(0.0, min(1.0, value)), color=color, bgcolor=track, bar_height=height,
                              border_radius=height)

    def divider(self) -> ft.Divider:
        return ft.Divider(height=1, thickness=1, color=self.p.divider)

    # ── 배경 · 화면 틀 ─────────────────────────────────
    def backdrop(self, night: bool = False) -> ft.Control:
        """글래스: 시안의 흐린 사진 배경(하늘 + 초원 보케). 그 밖: 단색."""
        if not self.is_glass:
            return ft.Container(expand=True, bgcolor=self.p.bg)
        dark = self.dark or night
        # 하늘(위) → 흐린 초원(아래). 시안처럼 아래쪽은 짙은 초록, 그 위에 흐린 꽃·빛 보케
        sky = ["#0b1020", "#1b2336", "#1d2b1e", "#101a12"] if dark else ["#6f767f", "#9ea3a9", "#6f7d5c", "#3c5530"]
        layers: list[ft.Control] = [ft.Container(expand=True, gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER, colors=sky, stops=[0.0, 0.5, 0.76, 1.0]))]
        bokeh = [
            # (가로, 세로 0~1, 지름, 색) — 시안 photoBg()의 광원·꽃 자리
            (0.6, 0.0, 380, alpha("#ffffff", 0.32 if dark else 0.8)),
            (0.1, 0.8, 120, alpha("#6f7f8f", 0.22) if dark else alpha("#f1efe6", 0.55)),
            (0.36, 0.75, 90, alpha("#6f7f8f", 0.2) if dark else alpha("#f1efe6", 0.5)),
            (0.72, 0.77, 130, alpha("#6f7f8f", 0.22) if dark else alpha("#f1efe6", 0.55)),
            (0.88, 0.86, 100, alpha("#6f7f8f", 0.2) if dark else alpha("#f1efe6", 0.45)),
            (0.22, 0.92, 140, alpha("#6f7f8f", 0.18) if dark else alpha("#f1efe6", 0.4)),
            (0.42, 0.8, 30, alpha("#e8c35a", 0.25 if dark else 0.75)),
            (0.76, 0.73, 22, alpha("#e8c35a", 0.25 if dark else 0.75)),
            (0.26, 0.85, 18, alpha("#e8c35a", 0.25 if dark else 0.7)),
        ]
        for x, y, size, c in bokeh:
            layers.append(ft.Container(
                width=size, height=size, border_radius=size, align=ft.Alignment(x * 2 - 1, y * 2 - 1),
                gradient=ft.RadialGradient(colors=[c, ft.Colors.TRANSPARENT]),
            ))
        if dark:
            for x, y in ((0.1, 0.1), (0.82, 0.07), (0.66, 0.16), (0.28, 0.24), (0.9, 0.27), (0.48, 0.05)):
                layers.append(ft.Container(width=3, height=3, bgcolor="#ffffff", border_radius=3, align=ft.Alignment(x * 2 - 1, y * 2 - 1)))
        return ft.Stack(layers, expand=True)

    def nav(self, selected: int, on_change: Callable[[int], None], badges: dict[int, int] | None = None) -> ft.Control:
        """하단 탭 5개: 홈 · 둘러보기 · 서재 · 함께 · 나."""
        items = [
            (ft.Icons.HOME_OUTLINED, ft.Icons.HOME_ROUNDED, "홈"),
            (ft.Icons.EXPLORE_OUTLINED, ft.Icons.EXPLORE, "둘러보기"),
            (ft.Icons.AUTO_STORIES_OUTLINED, ft.Icons.AUTO_STORIES, "서재"),
            (ft.Icons.PEOPLE_OUTLINE, ft.Icons.PEOPLE, "함께"),
            (ft.Icons.PERSON_OUTLINE, ft.Icons.PERSON, "나"),
        ]
        badges = badges or {}
        if self.is_glass:
            cells = []
            for i, (ic, ic_on, label) in enumerate(items):
                on = i == selected
                icon = ft.Icon(ic_on if on else ic, size=22, color="#ffffff")
                if badges.get(i):
                    icon = ft.Stack([icon, ft.Container(width=8, height=8, bgcolor="#ff5a5f", border_radius=8, right=0, top=0,
                                                        border=ft.Border.all(1.5, alpha("#ffffff", 0.9)))], width=24, height=24)
                cells.append(ft.Container(
                    content=ft.Column([icon, self.text(label, 10, "semibold" if on else "regular", color=alpha("#ffffff", 1 if on else 0.72))],
                                      spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=7), border_radius=9999, expand=True,
                    bgcolor=alpha("#ffffff", 0.3) if on else None, animate=ft.Animation(260, SPRING),
                    on_click=lambda e, i=i: on_change(i), key=f"tab-{i}",
                ))
            return ft.Container(
                content=ft.Row(cells, spacing=2),
                margin=ft.Margin.only(left=16, right=16, bottom=18), padding=7, border_radius=9999,
                blur=ft.Blur(30, 30), bgcolor=alpha("#ffffff", 0.18), border=ft.Border.all(1, alpha("#ffffff", 0.38)),
                shadow=ft.BoxShadow(blur_radius=30, offset=ft.Offset(0, 10), color=alpha("#000000", 0.18)),
            )
        dests = [ft.NavigationBarDestination(icon=ic, selected_icon=ic_on, label=label) for ic, ic_on, label in items]
        if self.name == CUPERTINO:
            return ft.CupertinoNavigationBar(destinations=dests, selected_index=selected, active_color=self.p.accent,
                                             bgcolor=alpha(self.p.surface, 0.94), on_change=lambda e: on_change(int(e.control.selected_index)))
        return ft.NavigationBar(destinations=dests, selected_index=selected, bgcolor=self.p.surface,
                                indicator_color=alpha(self.p.accent, 0.18),
                                on_change=lambda e: on_change(int(e.control.selected_index)))


def pressable(box: ft.Container, on_click: Callable) -> ft.Container:
    """누르는 순간 살짝 작아졌다가(0.97) 스프링으로 돌아오는 손맛 + 진동."""
    box.animate_scale = ft.Animation(260, SPRING)

    def down(e):
        box.scale = 0.97
        box.update()

    async def click(e):
        box.scale = 1.0
        box.update()
        result = on_click(e)
        if hasattr(result, "__await__"):
            await result

    box.on_tap_down = down
    box.on_click = click
    return box
