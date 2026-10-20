"""화면의 공통 틀.

화면 하나 = Screen 하나 = ft.View 하나. 앱은 화면들을 쌓아(stack) page.views로 보여 준다.
- 처음에는 스켈레톤을 그리고 load()에서 데이터를 받아 다시 그린다.
- 오프라인·오류면 '다시 시도' 화면을 보여 준다.
- 탭 화면(홈·둘러보기·서재·함께·나)은 하단 탭을 갖고, 그 위에 쌓인 화면은 뒤로가기(밀어서·버튼)를 갖는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import flet as ft

from saipr.core.api import ApiError, Offline
from saipr.ui import widgets as w
from saipr.ui.theme import alpha

if TYPE_CHECKING:
    from saipr.app import App


class Screen:
    tab: int | None = None  # 탭 화면이면 그 번호
    title: str = ""  # 상단 제목(쌓인 화면)
    large_title: str | None = None  # 본문 맨 위 큰 제목(탭 화면)
    night: bool = False  # 글래스에서 밤 배경 (레이스·배틀)
    padded: bool = True

    def __init__(self, app: App, route: str, **params: Any) -> None:
        self.app = app
        self.route = route
        self.params = params
        self.data: Any = None
        self.error: str | None = None
        self.loading = True
        self.body = ft.ListView(expand=True, spacing=16, padding=self._padding(), controls=[])
        self.view: ft.View | None = None

    @property
    def d(self):
        return self.app.design

    @property
    def api(self):
        return self.app.api

    # ── 그리기 ─────────────────────────────────────
    def _padding(self) -> ft.Padding:
        bottom = 120 if (self.tab is not None and self.app.design.is_glass) else 32
        return ft.Padding.only(left=20, right=20, top=8, bottom=bottom) if self.padded else ft.Padding.all(0)

    def content(self) -> list[ft.Control]:
        """데이터(self.data)로 본문을 만든다. 하위 화면이 구현한다."""
        return []

    def skeleton(self) -> list[ft.Control]:
        return [w.skeleton(self.d, 3), w.skeleton(self.d, 2), w.skeleton(self.d, 4)]

    def actions(self) -> list[ft.Control]:
        return []

    def _render_body(self) -> list[ft.Control]:
        head: list[ft.Control] = []
        if self.large_title:
            head.append(ft.Container(self.d.title(self.large_title, 34), padding=ft.Padding.only(top=6, bottom=2)))
        if self.error and self.data is None:
            return [*head, w.error_state(self.d, self.error, lambda e: self.app.run(self.reload()))]
        if self.loading and self.data is None:
            return [*head, *self.skeleton()]
        return [*head, *self.content()]

    def refresh(self) -> None:
        if isinstance(self.body, ft.ListView):
            self.body.padding = self._padding()
        self.body.controls = self._render_body()
        if w.mounted(self.view):
            self.body.update()

    def header(self) -> ft.Control | None:
        if self.tab is not None:
            acts = self.actions()
            return ft.Container(ft.Row(acts, alignment=ft.MainAxisAlignment.END), padding=ft.Padding.only(right=8, top=4)) if acts else None
        back = ft.IconButton(icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_color=self.d.p.fg, icon_size=20,
                             on_click=lambda e: self.app.pop(), tooltip="뒤로", key="back")
        return ft.Container(
            ft.Row([back, ft.Container(self.d.text(self.title, 17, "semibold", max_lines=1), expand=True), *self.actions()],
                   spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.only(left=4, right=8, top=2, bottom=2),
        )

    def build(self) -> ft.View:
        d = self.d
        self.body.controls = self._render_body()
        column_items: list[ft.Control] = []
        h = self.header()
        if h:
            column_items.append(h)
        column_items.append(self.body)
        layers: list[ft.Control] = [d.backdrop(night=self.night), ft.SafeArea(ft.Column(column_items, spacing=0, expand=True), expand=True)]
        nav_bar = None
        if self.tab is not None:
            nav = d.nav(self.tab, self.app.go_tab, badges={4: self.app.unread} if self.app.unread else None)
            if d.is_glass:
                layers.append(ft.Container(ft.SafeArea(nav, avoid_intrusions_top=False), bottom=0, left=0, right=0))
            else:
                nav_bar = nav
        overlay = self.overlay()
        if overlay:
            layers.extend(overlay)
        self.view = ft.View(
            route=self.route, padding=0, spacing=0, bgcolor=d.p.bg if not d.is_glass else "#9ea3a9",
            controls=[ft.Stack(layers, expand=True)], navigation_bar=nav_bar,
            can_pop=self.tab is None,
        )
        return self.view

    def overlay(self) -> list[ft.Control]:
        """화면 위에 떠 있는 것(리더의 잠금 알약 등)."""
        return []

    # ── 데이터 ─────────────────────────────────────
    async def load(self) -> None:
        """하위 화면이 구현: self.data를 채운다. 예외는 reload()가 처리한다."""

    async def reload(self) -> None:
        self.loading, self.error = True, None
        if self.data is None:
            self.refresh()
        try:
            await self.load()
        except Offline as e:
            self.error = e.message
        except ApiError as e:
            if e.status == 401:
                await self.app.session_expired()
                return
            self.error = e.message
        finally:
            self.loading = False
        self.refresh()

    async def on_show(self) -> None:
        """화면이 맨 위로 올라왔을 때 (처음·뒤로가기로 돌아왔을 때)."""
        if self.data is None or self.stale():
            await self.reload()

    def stale(self) -> bool:
        return self.tab is not None  # 탭 화면은 돌아올 때마다 새로고침

    def on_hide(self) -> None:
        """화면이 스택에서 빠질 때 — 실시간 구독 해제 등."""


def chip_row(controls: list[ft.Control]) -> ft.Row:
    return ft.Row(controls, spacing=8, scroll=ft.ScrollMode.HIDDEN)


def subtle(d, text: str) -> ft.Control:
    return ft.Container(d.text(text, 12, muted=True), padding=ft.Padding.symmetric(horizontal=4))


def soft_box(d, content: ft.Control, padding: float = 14) -> ft.Control:
    return ft.Container(content, padding=padding, border_radius=16, bgcolor=alpha(d.p.fg, 0.06))
