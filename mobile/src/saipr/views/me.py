"""나 — 프로필 · 통계(오늘 · 주간 그래프 · 12주 잔디 · 연간 목표) · 배지 · 포인트 · 알림 · 설정."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import flet as ft
import flet_charts as fch

from saipr.app import gather_safe
from saipr.core import fmt
from saipr.ui import widgets as w
from saipr.ui.theme import CUPERTINO, DESIGNS, GLASS, MATERIAL, alpha
from saipr.views.base import Screen

WEEK = "월화수목금토일"


class MeScreen(Screen):
    tab = 4

    async def load(self):
        stats, badges, points, me = await gather_safe(
            self.api.get("/me/stats"), self.api.get("/me/badges"), self.api.get("/points"), self.api.get("/auth/me"))
        if me:
            self.app.user = me
            await self.app.store.set("user", me)
        self.data = {"stats": stats, "badges": badges or [], "points": points}

    def actions(self):
        n = self.app.unread
        bell = self.d.icon_button(ft.Icons.NOTIFICATIONS_OUTLINED if not n else ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED,
                                  lambda e: self.app.push(NotificationsScreen(self.app, "/notifications")), "알림", key="bell")
        gear = self.d.icon_button(ft.Icons.SETTINGS_OUTLINED, lambda e: self.app.push(SettingsScreen(self.app, "/settings")), "설정", key="settings")
        return [bell, gear]

    def content(self):
        d = self.d
        u = self.app.user or {}
        st = self.data["stats"] or {}
        out: list[ft.Control] = [ft.Row([
            w.avatar(d, u, 64),
            ft.Column([d.text(u.get("nickname", ""), 24, "bold"), d.caption(u.get("bio") or u.get("email") or "")], spacing=2, expand=True),
            d.icon_button(ft.Icons.EDIT_OUTLINED, lambda e: self.edit_profile(), "프로필 수정"),
        ], spacing=14)]

        goal = st.get("daily_goal_minutes") or u.get("daily_goal_minutes") or 20
        today = st.get("today_minutes") or 0
        out.append(d.card(ft.Row([
            w.ring(d, today / goal if goal else 0, 86, 9, center=ft.Column([d.text(str(int(today)), 22, "bold"), d.caption("분", size=11)],
                                                                         spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)),
            ft.Column([
                d.text("오늘의 독서", 16, "bold"),
                d.caption(f"목표 {fmt.minutes(goal)} 중 {fmt.minutes(today)}"),
                d.text(f"🔥 {st.get('streak', 0)}일 연속 · 최고 {st.get('best_streak', 0)}일", 14, "medium"),
            ], spacing=4, expand=True),
        ], spacing=18), padding=20))

        out.append(ft.Row([
            w.stat(d, str(st.get("books_done", 0)), "완독", ft.Icons.MENU_BOOK_ROUNDED),
            w.stat(d, fmt.minutes(st.get("total_minutes", 0)), "총 독서", ft.Icons.SCHEDULE_ROUNDED),
            w.stat(d, str(st.get("highlights", 0)), "밑줄", ft.Icons.FORMAT_QUOTE_ROUNDED),
        ], spacing=10))

        if st.get("week"):
            out.append(d.section("이번 주"))
            out.append(d.card(self._week_chart(st["week"], goal), padding=ft.Padding.only(left=12, right=16, top=18, bottom=8)))
        if st.get("heatmap"):
            out.append(d.section("최근 12주"))
            out.append(d.card(self._heatmap(st["heatmap"]), padding=16))
        yearly = st.get("yearly_goal_books") or u.get("yearly_goal_books") or 12
        done_year = st.get("books_done_year", 0)
        out.append(d.card(ft.Row([
            w.ring(d, done_year / yearly if yearly else 0, 56, 6, center=d.text(str(done_year), 15, "bold")),
            ft.Column([d.text(f"올해 목표 {yearly}권", 15, "semibold"), d.caption(f"{max(0, yearly - done_year)}권 남았어요" if done_year < yearly else "올해 목표를 이뤘어요! 🎉")],
                      spacing=2, expand=True),
        ], spacing=16), padding=18, radius=22))

        badges = self.data["badges"]
        if badges:
            earned = sum(1 for b in badges if b.get("earned"))
            out.append(d.section(f"배지 {earned}/{len(badges)}"))
            out.append(ft.Row([self._badge(b) for b in badges], wrap=True, spacing=10, run_spacing=10))

        pts = self.data["points"]
        if pts:
            out.append(d.section("포인트 · 챌린지"))
            rows: list[ft.Control] = [ft.Row([d.text(f"{pts['balance']:,}P", 28, "bold"), d.caption("청크 1P · 완독 50P · 배틀 승리 100P")],
                                             alignment=ft.MainAxisAlignment.SPACE_BETWEEN)]
            for c in pts.get("challenges", []):
                rows.append(ft.Column([
                    ft.Row([d.text(c["title"], 14), d.caption(f"{min(c['progress'], c['goal'])}/{c['goal']} · +{c['reward_points']}P", size=12)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    d.progress(min(1, c["progress"] / c["goal"]) if c["goal"] else 0, soft=c["progress"] < c["goal"]),
                ], spacing=6))
            out.append(d.card(ft.Column(rows, spacing=14), padding=20))
        return out

    def _week_chart(self, week: list[dict], goal: int) -> ft.Control:
        d = self.d
        color = "#ffffff" if d.is_glass else d.p.accent
        top = max([day.get("minutes", 0) for day in week] + [goal, 10])
        groups = []
        for i, day in enumerate(week):
            dt = fmt.parse(day.get("date") + "T00:00:00+09:00") if day.get("date") else None
            m = day.get("minutes", 0)
            groups.append(fch.BarChartGroup(x=i, rods=[fch.BarChartRod(
                from_y=0, to_y=m, width=18, color=color if m >= goal else alpha(color, 0.55),
                border_radius=6, tooltip=f"{fmt.minutes(m)}",
            )]))
            _ = dt
        labels = []
        for i, day in enumerate(week):
            try:
                wd = datetime.fromisoformat(day["date"]).weekday()
            except (KeyError, ValueError):
                wd = i
            labels.append(fch.ChartAxisLabel(value=i, label=d.text(WEEK[wd], 11, muted=True)))
        return fch.BarChart(
            groups=groups, max_y=top * 1.15, height=150, interactive=True,
            bottom_axis=fch.ChartAxis(labels=labels, label_size=24),
            left_axis=fch.ChartAxis(show_labels=False, label_size=0),
            horizontal_grid_lines=fch.ChartGridLines(color=alpha(d.p.fg, 0.08), width=1, dash_pattern=[3, 3]),
        )

    def _heatmap(self, heat: list[dict]) -> ft.Control:
        d = self.d
        base = "#ffffff" if d.is_glass else ("#30a46c" if d.name != CUPERTINO else "#34c759")
        cols = []
        days = heat[-84:]
        for c in range(0, len(days), 7):
            col = []
            for day in days[c:c + 7]:
                m = day.get("minutes", 0)
                level = 0 if m <= 0 else (0.35 if m < 10 else (0.6 if m < 30 else 0.95))
                col.append(ft.Container(width=20, height=20, border_radius=5,
                                        bgcolor=alpha(base, level) if level else alpha(d.p.fg, 0.08), tooltip=f"{day.get('date')} · {fmt.minutes(m)}"))
            cols.append(ft.Column(col, spacing=5))
        legend = ft.Row([d.caption("적게", size=11), *[ft.Container(width=10, height=10, border_radius=3, bgcolor=alpha(base, lv) if lv else alpha(d.p.fg, 0.08)) for lv in (0, 0.35, 0.6, 0.95)],
                         d.caption("많이", size=11)], spacing=4, alignment=ft.MainAxisAlignment.END)
        return ft.Column([ft.Row(cols, spacing=2, alignment=ft.MainAxisAlignment.SPACE_BETWEEN), legend], spacing=10)

    def _badge(self, b: dict) -> ft.Control:
        d = self.d
        on = b.get("earned")
        return ft.Container(ft.Column([
            ft.Text(b.get("icon") or "🏅", size=26, opacity=1 if on else 0.35),
            d.text(b["title"], 12, "semibold", align=ft.TextAlign.CENTER, max_lines=1),
            d.text("획득" if on else f"{min(b.get('progress', 0), b.get('goal', 1))}/{b.get('goal', 1)}", 10, muted=True, align=ft.TextAlign.CENTER),
        ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            width=96, padding=10, border_radius=18, tooltip=b.get("description"),
            bgcolor=(alpha("#ffffff", 0.18) if d.is_glass else d.p.surface) if on else (alpha("#ffffff", 0.06) if d.is_glass else alpha(d.p.fg, 0.04)),
            border=ft.Border.all(1, alpha("#ffffff", 0.3)) if d.is_glass else None)

    def edit_profile(self) -> None:
        u = self.app.user or {}
        nick = ft.TextField(label="닉네임", value=u.get("nickname", ""), max_length=40)
        bio = ft.TextField(label="한 줄 소개", value=u.get("bio") or "", max_length=120)
        goal = ft.Slider(min=5, max=120, divisions=23, value=u.get("daily_goal_minutes") or 20, label="하루 {value}분")
        yearly = ft.Slider(min=1, max=52, divisions=51, value=u.get("yearly_goal_books") or 12, label="올해 {value}권")

        async def save(e):
            me = await self.app.guard(self.api.put("/auth/me/profile", {
                "nickname": nick.value, "bio": bio.value, "daily_goal_minutes": int(goal.value), "yearly_goal_books": int(yearly.value)}), ok="저장했어요")
            if me:
                self.app.user = me
                await self.app.store.set("user", me)
                self.app.close_dialog()
                await self.reload()

        self.app.sheet(ft.Column([
            ft.Text("프로필 · 목표", size=20, font_family="Pretendard Bold"),
            nick, bio,
            ft.Text("하루 독서 목표", size=13, font_family="Pretendard", color="#6c6c70"), goal,
            ft.Text("올해 완독 목표", size=13, font_family="Pretendard", color="#6c6c70"), yearly,
            ft.Button(content=ft.Text("저장", font_family="Pretendard SemiBold"), on_click=save),
        ], spacing=10, tight=True))


class NotificationsScreen(Screen):
    title = "알림"

    async def load(self):
        self.data = await self.api.get("/notifications")
        if any(not n.get("read") for n in self.data):
            try:
                await self.api.post("/notifications/read")
            except Exception:
                pass
        self.app.unread = 0

    def content(self):
        d = self.d
        if not self.data:
            return [w.empty(d, ft.Icons.NOTIFICATIONS_NONE_ROUNDED, "새 알림이 없어요", "친구가 나를 앞지르거나 내 문단에 반응하면 알려 드려요.\n밤 10시~아침 8시에는 모아 두었다가 보내요.")]
        icons = {"overtaken": "🏃", "reaction": "💬", "room_joined": "👋", "battle": "⚔️", "battle_ending": "⏰", "battle_result": "🏆",
                 "challenge": "🎯", "team_joined": "🤝", "cheer": "👏", "follow": "➕", "test": "🔔"}
        rows = [w.list_row(d, ft.Text(icons.get(n["kind"], "🔔"), size=22), n["body"], fmt.ago(n.get("created_at")),
                           ft.Container(width=8, height=8, border_radius=8, bgcolor="#ff5a5f") if not n.get("read") else None,
                           on_click=(lambda e, n=n: self.app.open_link(n["link"])) if n.get("link") else None)
                for n in self.data]
        return [d.card(ft.Column(rows, spacing=0), padding=ft.Padding.symmetric(horizontal=16, vertical=6))]


class SettingsScreen(Screen):
    title = "설정"

    def __init__(self, app, route):
        super().__init__(app, route)
        self.data = True
        self.loading = False

    async def on_show(self):
        self.refresh()

    def content(self):
        d = self.d
        u = self.app.user or {}

        def design_card(name: str, label: str, desc: str, colors: list[str]) -> ft.Control:
            on = d.name == name
            return ft.Container(ft.Column([
                ft.Container(height=56, border_radius=12, gradient=ft.LinearGradient(colors=colors),
                             content=ft.Container(width=34, height=18, border_radius=6, bgcolor=alpha("#ffffff", 0.7), margin=ft.Margin.only(left=10, top=10))),
                d.text(label, 14, "bold"), d.text(desc, 11, muted=True, max_lines=2),
            ], spacing=6), expand=True, padding=10, border_radius=18,
                border=ft.Border.all(2, d.p.accent if (on and not d.is_glass) else ("#ffffff" if on else alpha(d.p.fg, 0.15))),
                on_click=lambda e: self.app.run(self.app.set_design(name)), key=f"design-{name}")

        out: list[ft.Control] = [
            d.section("디자인"),
            ft.Row([
                design_card(GLASS, DESIGNS[GLASS], "흐린 사진 위 유리", ["#6f767f", "#9ea3a9", "#55703f"]),
                design_card(MATERIAL, DESIGNS[MATERIAL], "안드로이드 머티리얼 3", ["#e0e5ff", "#4a5ba8"]),
                design_card(CUPERTINO, DESIGNS[CUPERTINO], "아이폰 기본 스타일", ["#f2f2f7", "#ffffff"]),
            ], spacing=10),
            d.card(ft.Column([
                ft.Row([d.text("다크 모드", 15, expand=True), d.switch(d.dark, lambda e: self.app.run(self.app.set_design(dark=bool(e.control.value))))]),
                d.divider(),
                ft.Row([ft.Column([d.text("스포일러 가드", 15), d.caption("아직 안 읽은 곳의 반응은 숨겨요", size=12)], spacing=2, expand=True),
                        d.switch(bool(u.get("spoiler_guard", True)), lambda e: self.app.run(self.set_guard(bool(e.control.value))))]),
            ], spacing=12), padding=18),
            d.section("계정"),
            d.card(ft.Column([
                w.list_row(d, ft.Icon(ft.Icons.DNS_OUTLINED, color=d.p.muted), "서버", self.api.base_url),
                w.list_row(d, ft.Icon(ft.Icons.BADGE_OUTLINED, color=d.p.muted), "친구 코드", u.get("friend_code") or "-",
                           d.icon_button(ft.Icons.COPY_ROUNDED, lambda e: self.app.run(self.app.copy(u.get("friend_code") or "")))),
                w.list_row(d, ft.Icon(ft.Icons.LOGOUT_ROUNDED, color=d.p.danger), "로그아웃", None, on_click=lambda e: self.app.run(self.app.logout())),
            ], spacing=0), padding=ft.Padding.symmetric(horizontal=16, vertical=6)),
            d.caption("함께읽기 1.0 · 본문은 저작권이 끝난 공개 도서(위키문헌)만 제공해요. 글꼴: Pretendard, 고운바탕 (OFL)", size=11),
        ]
        return out

    async def set_guard(self, on: bool) -> None:
        me = await self.app.guard(self.api.put("/auth/me/profile", {"spoiler_guard": on}))
        if me:
            self.app.user = me
            await self.app.store.set("user", me)
            self.app.toast("스포일러 가드를 켰어요" if on else "스포일러 가드를 껐어요. 앞선 반응도 보여요")


_ = (UTC, timedelta)
