"""공용 위젯 — 표지 · 아바타 · 스켈레톤 · 빈 화면 · 오류 화면 · 통계 타일 · 링."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from saipr.ui.theme import Design, alpha, avatar_color, cover_color


def mounted(control: ft.Control | None) -> bool:
    """화면에 붙어 있는가. Flet 1.0은 붙기 전에 .page를 읽으면 예외를 낸다."""
    if control is None:
        return False
    try:
        return control.page is not None
    except RuntimeError:
        return False


def cover(d: Design, book: dict, width: float = 54, height: float | None = None, hero: str | None = None) -> ft.Control:
    """책 표지. 표지 이미지가 있으면 쓰고, 없으면 시안의 '색 + 제목' 표지를 그린다(제본선·반사광 포함)."""
    height = height or width * 1.41
    title = book.get("title", "")
    bg = cover_color(book.get("id"), book.get("cover_color"))
    url = book.get("cover_url")
    radius = max(4, width * 0.09)
    face: ft.Control
    if url:
        face = ft.Image(src=url, width=width, height=height, fit=ft.BoxFit.COVER, border_radius=radius,
                        error_content=_typo_cover(title, book.get("author"), bg, width, height, radius))
    else:
        face = _typo_cover(title, book.get("author"), bg, width, height, radius)
    box = ft.Container(face, width=width, height=height, border_radius=radius,
                       shadow=ft.BoxShadow(blur_radius=16, offset=ft.Offset(0, 8), color=alpha("#000000", 0.28)))
    return ft.Hero(tag=hero, content=box) if hero else box


def _typo_cover(title: str, author: str | None, bg: str, w: float, h: float, r: float) -> ft.Control:
    big = w >= 90
    text = ft.Column([
        ft.Text(title, size=max(9, w * (0.15 if big else 0.2)), font_family="Gowun Batang Bold", color="#ffffff",
                max_lines=4, overflow=ft.TextOverflow.ELLIPSIS, style=ft.TextStyle(height=1.25)),
        *([ft.Text(author, size=max(8, w * 0.09), font_family="Pretendard", color=alpha("#ffffff", 0.85), max_lines=1)] if (author and big) else []),
    ], spacing=6, tight=True)
    return ft.Stack([
        ft.Container(width=w, height=h, border_radius=r, bgcolor=bg),
        # 제본선 그림자와 반사광 — 색 위에 겹친다 (gradient는 bgcolor를 덮어 버리므로 따로 둔다)
        ft.Container(width=w, height=h, border_radius=r, gradient=ft.LinearGradient(
            begin=ft.Alignment.CENTER_LEFT, end=ft.Alignment.CENTER_RIGHT,
            colors=[alpha("#000000", 0.28), alpha("#000000", 0.0), alpha("#ffffff", 0.18), alpha("#ffffff", 0.0)],
            stops=[0.0, 0.12, 0.16, 0.3])),
        ft.Container(text, width=w, height=h, padding=ft.Padding.only(left=w * 0.16, top=w * 0.14, right=w * 0.08)),
    ], width=w, height=h)


def avatar(d: Design, user: dict | None, size: float = 28, me: bool = False) -> ft.Control:
    user = user or {}
    name = "나" if me else (user.get("nickname") or "?")[:1]
    color = "#1d1d1f" if me else avatar_color(user.get("id"), user.get("avatar_color"))
    return ft.Container(
        content=ft.Text(name, size=size * 0.42, font_family="Pretendard SemiBold", color="#ffffff"),
        width=size, height=size, border_radius=size, bgcolor=color, alignment=ft.Alignment.CENTER,
        border=ft.Border.all(1.5, alpha("#ffffff", 0.85)) if d.is_glass else None,
    )


def avatars(d: Design, users: list[dict], size: float = 28, limit: int = 4) -> ft.Control:
    shown = users[:limit]
    return ft.Stack([ft.Container(avatar(d, u, size), left=i * (size - 8)) for i, u in enumerate(shown)],
                    width=size + max(0, len(shown) - 1) * (size - 8), height=size)


def skeleton(d: Design, lines: int = 3, height: float = 96) -> ft.Control:
    base = alpha(d.p.fg, 0.08)
    blocks = [ft.Container(height=14 if i else 22, width=None if i else 160, bgcolor=base, border_radius=8) for i in range(lines)]
    return ft.Shimmer(
        content=d.card(ft.Column(blocks, spacing=12), padding=20),
        base_color=alpha(d.p.fg, 0.06), highlight_color=alpha(d.p.fg, 0.18), period=1400,
    )


def empty(d: Design, icon: str, title: str, body: str, action: str | None = None, on_action: Callable | None = None) -> ft.Control:
    return d.card(ft.Column([
        ft.Icon(icon, size=34, color=d.p.muted),
        d.text(title, 17, "bold"),
        d.text(body, 14, muted=True, align=ft.TextAlign.CENTER),
        *([d.button(action, on_action, kind="secondary")] if action else []),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10), padding=28)


def error_state(d: Design, message: str, on_retry: Callable) -> ft.Control:
    return d.card(ft.Column([
        ft.Icon(ft.Icons.CLOUD_OFF_ROUNDED, size=34, color=d.p.muted),
        d.text("불러오지 못했어요", 17, "bold"),
        d.text(message, 14, muted=True, align=ft.TextAlign.CENTER),
        d.button("다시 시도", on_retry, icon=ft.Icons.REFRESH_ROUNDED, kind="secondary"),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10), padding=28)


def ring(d: Design, value: float, size: float = 64, stroke: float = 7, center: ft.Control | None = None,
         color: str | None = None) -> ft.Control:
    value = max(0.0, min(1.0, value))
    c = color or ("#ffffff" if d.is_glass else d.p.accent)
    return ft.Stack([
        ft.Container(ft.ProgressRing(value=value, stroke_width=stroke, color=c, bgcolor=alpha(d.p.fg, 0.15),
                                     stroke_cap=ft.StrokeCap.ROUND), width=size, height=size),
        ft.Container(center, width=size, height=size, alignment=ft.Alignment.CENTER) if center else ft.Container(),
    ], width=size, height=size)


def stat(d: Design, value: str, label: str, icon: str | None = None) -> ft.Control:
    return d.card(ft.Column([
        *([ft.Icon(icon, size=18, color=d.p.muted)] if icon else []),
        d.text(value, 24, "bold"),
        d.caption(label),
    ], spacing=4, tight=True), padding=16, expand=True)


def list_row(d: Design, leading: ft.Control | None, title: str, subtitle: str | None = None,
             trailing: ft.Control | None = None, on_click: Callable | None = None) -> ft.Control:
    row = ft.Row([
        *([leading] if leading else []),
        ft.Column([d.text(title, 15, "semibold", max_lines=1), *([d.caption(subtitle, max_lines=2)] if subtitle else [])],
                  spacing=2, expand=True, tight=True),
        *([trailing] if trailing else []),
    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    box = ft.Container(row, padding=ft.Padding.symmetric(vertical=10), on_click=on_click)
    return box


def pill(d: Design, text: str, dark: bool = False, icon: str | None = None) -> ft.Control:
    fg = "#ffffff" if (dark or d.is_glass) else d.p.fg
    bg = alpha("#1d1d1f", 0.72) if dark else (alpha("#ffffff", 0.14) if d.is_glass else alpha(d.p.fg, 0.07))
    return ft.Container(
        ft.Row([*( [ft.Icon(icon, size=14, color=fg)] if icon else []), ft.Text(text, size=12, font_family="Pretendard Medium", color=fg)],
               spacing=6, tight=True),
        padding=ft.Padding.symmetric(horizontal=12, vertical=6), border_radius=9999, bgcolor=bg,
        border=ft.Border.all(1, alpha("#ffffff", 0.3)) if (dark or d.is_glass) else None,
    )
