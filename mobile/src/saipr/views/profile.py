"""다른 사람의 프로필 — 팔로우 · 응원 · 통계 · 읽는 책 · 공개 밑줄."""

from __future__ import annotations

import flet as ft

from saipr.core import fmt
from saipr.ui import widgets as w
from saipr.views.base import Screen


class UserScreen(Screen):
    def __init__(self, app, route, user_id: int, preview: dict | None = None):
        super().__init__(app, route)
        self.user_id = user_id
        self.preview = preview or {}
        self.title = self.preview.get("nickname", "")

    def stale(self):
        return self.data is None

    async def load(self):
        self.data = await self.api.get(f"/users/{self.user_id}")
        self.title = self.data.get("nickname", "")

    def content(self):
        d, u = self.d, self.data
        me = u["id"] == (self.app.user or {}).get("id")
        stats = u.get("stats") or {}
        head = ft.Column([
            w.avatar(d, u, 84),
            d.text(u["nickname"], 26, "bold"),
            *([d.text(u["bio"], 14, muted=True, align=ft.TextAlign.CENTER)] if u.get("bio") else []),
            d.caption(f"팔로워 {u.get('followers', 0)} · 팔로잉 {u.get('following', 0)}"),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8)
        out: list[ft.Control] = [head]
        if not me:
            out.append(ft.Row([
                d.button("팔로잉" if u.get("is_following") else "팔로우", lambda e: self.app.run(self.toggle()),
                         kind="secondary" if u.get("is_following") else "primary", expand=True, key="follow"),
                d.button("👏 응원하기", lambda e: self.app.run(self.cheer()), kind="secondary", expand=True),
            ], spacing=10))
        out.append(ft.Row([
            w.stat(d, str(stats.get("books_done", 0)), "완독한 책", ft.Icons.MENU_BOOK_ROUNDED),
            w.stat(d, f"{stats.get('streak', 0)}일", "연속 읽기", ft.Icons.LOCAL_FIRE_DEPARTMENT_ROUNDED),
            w.stat(d, fmt.minutes(stats.get("minutes_week", 0)), "이번 주", ft.Icons.SCHEDULE_ROUNDED),
        ], spacing=10))
        reading = u.get("reading") or []
        if reading:
            from saipr.views.book import BookScreen

            out.append(d.section("지금 읽는 책"))
            out.append(ft.Row([ft.Container(ft.Column([
                w.cover(d, b, 96), d.text(b["title"], 13, "semibold", max_lines=1, width=96),
                d.text(f"{b.get('progress_pct', 0)}%", 11, muted=True)], spacing=6, tight=True),
                on_click=lambda e, b=b: self.app.push(BookScreen(self.app, f"/book/{b['id']}", book_id=b["id"], preview=b))) for b in reading],
                spacing=14, scroll=ft.ScrollMode.HIDDEN))
        hs = u.get("highlights") or []
        if hs:
            out.append(d.section("공개한 밑줄"))
            for h in hs:
                out.append(d.card(ft.Column([
                    ft.Text(f"“{h['quote']}”", size=15, font_family="Gowun Batang", color=d.p.fg),
                    *([d.text(h["note"], 13, muted=True)] if h.get("note") else []),
                    d.caption(f"「{(h.get('book') or {}).get('title', '')}」 · {fmt.ago(h.get('created_at'))}", size=12),
                ], spacing=8), padding=16, radius=22))
        return out

    async def toggle(self):
        if self.data.get("is_following"):
            ok = await self.app.guard(self.api.delete(f"/users/{self.user_id}/follow"))
        else:
            ok = await self.app.guard(self.api.post(f"/users/{self.user_id}/follow"), ok=f"{self.data['nickname']}님을 팔로우했어요")
        if ok:
            self.app.haptic("medium")
            await self.reload()

    async def cheer(self):
        if await self.app.guard(self.api.post(f"/users/{self.user_id}/cheer"), ok="응원을 보냈어요 👏"):
            self.app.haptic("medium")
