"""홈 — 인사 · 오늘 목표 · 이어 읽기 · 친구 소식 · 내 읽기방 · 레이스."""

from __future__ import annotations

import flet as ft

from saipr.app import gather_safe
from saipr.core import fmt
from saipr.core.reading import kst_greeting
from saipr.ui import widgets as w
from saipr.views.base import Screen
from saipr.views.start import orb


class HomeScreen(Screen):
    tab = 0

    async def load(self):
        library, rooms, battles, stats, feed = await gather_safe(
            self.api.get("/library"), self.api.get("/rooms"), self.api.get("/battles"),
            self.api.get("/me/stats"), self.api.get("/feed", limit=6),
        )
        self.data = {"library": library or [], "rooms": rooms or [], "battles": battles or [],
                     "stats": stats, "feed": feed or []}

    def content(self):
        d, data, user = self.d, self.data, self.app.user or {}
        out: list[ft.Control] = []
        streak = (data["stats"] or {}).get("streak") or 0
        out.append(ft.Row([
            ft.Column([
                d.text(fmt.today_label() + (f" · 🔥 {streak}일 연속" if streak else ""), 14, muted=True),
                d.title(f"{kst_greeting()}\n함께 읽어요"),
            ], spacing=4, expand=True),
            ft.Container(orb(92) if d.is_glass else w.avatar(d, user, 52), on_click=lambda e: self.app.go_tab(4), tooltip="내 정보"),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER))

        out.append(self._continue_card(data["library"]))
        if data["stats"]:
            out.append(self._goal_card(data["stats"], user))

        friends = [a for a in data["feed"] if a.get("user", {}).get("id") != user.get("id")]
        if friends:
            out.append(d.section("친구 소식", "더 보기", lambda e: self.app.go_tab(3)))
            out.append(d.card(ft.Column([self._activity_row(a) for a in friends[:3]], spacing=4), padding=ft.Padding.symmetric(horizontal=18, vertical=10)))

        out.append(d.section("내 읽기방", "전체" if data["rooms"] else None, lambda e: self._open_together("rooms")))
        if data["rooms"]:
            for r in data["rooms"][:3]:
                out.append(self._room_card(r))
        else:
            out.append(d.card(ft.Row([ft.Icon(ft.Icons.GROUPS_2_OUTLINED, color=d.p.muted),
                                      d.text("책 화면에서 방을 만들거나 친구에게 받은 초대 코드로 들어가 보세요.", 14, muted=True, expand=True)], spacing=12),
                              padding=18, radius=22))
        active = [b for b in data["battles"] if b.get("status") != "finished"]
        for b in active[:2]:
            out.append(self._battle_card(b))
        return out

    def _continue_card(self, library: list[dict]) -> ft.Control:
        d = self.d
        reading = [e for e in library if e.get("shelf") == "reading"] or [e for e in library if e.get("shelf") == "want"]
        if not reading:
            return d.card(ft.Column([
                d.caption("첫 책"),
                d.text("무엇부터 읽어 볼까요?", 24, "bold"),
                d.caption("김유정의 「봄봄」·「동백꽃」, 현진건의 「운수 좋은 날」을 바로 읽을 수 있어요."),
                ft.Row([d.button("책 둘러보기", lambda e: self.app.go_tab(1), icon=ft.Icons.EXPLORE)], alignment=ft.MainAxisAlignment.END),
            ], spacing=10), padding=22)
        e = reading[0]
        book = {"id": e["book_id"], "title": e["title"], "author": e.get("author"), "cover_url": e.get("cover_url")}
        pct = e.get("progress_pct", 0)
        sub = f"{e.get('author') or '작자 미상'} · {'전문 읽기' if e.get('has_fulltext') else '진행률 기록'}"
        chunk = f" · {e.get('verified_chunk', -1) + 1} / {e.get('total_chunks')}쪽" if e.get("has_fulltext") else ""
        from saipr.views.book import BookScreen

        return d.card(ft.Column([
            ft.Row([
                w.cover(d, book, 64, hero=f"cover-{book['id']}"),
                ft.Column([d.caption("이어 읽기" if pct else "읽기 시작"),
                           d.text(e["title"], 26, "bold", max_lines=2),
                           d.caption(sub, max_lines=1)], spacing=4, expand=True),
            ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            d.progress(pct / 100),
            ft.Row([d.text(f"{pct}%{chunk}", 13), d.button("이어 읽기" if pct else "읽기 시작", lambda ev: self._read(e), key="continue")],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ], spacing=14), padding=22, on_click=lambda ev: self.app.push(BookScreen(self.app, f"/book/{book['id']}", book_id=book["id"], preview=book)))

    def _read(self, entry: dict) -> None:
        if entry.get("has_fulltext"):
            from saipr.views.reader import ReaderScreen

            self.app.push(ReaderScreen(self.app, f"/read/{entry['book_id']}", book_id=entry["book_id"]))
        else:
            from saipr.views.book import BookScreen

            self.app.push(BookScreen(self.app, f"/book/{entry['book_id']}", book_id=entry["book_id"]))

    def _goal_card(self, stats: dict, user: dict) -> ft.Control:
        d = self.d
        goal = stats.get("daily_goal_minutes") or user.get("daily_goal_minutes") or 20
        today = stats.get("today_minutes") or 0
        done = today >= goal
        yearly = stats.get("yearly_goal_books") or 12
        return d.card(ft.Row([
            w.ring(d, today / goal if goal else 0, 62, center=d.text(f"{int(today)}", 18, "bold")),
            ft.Column([
                d.text("오늘 목표 달성! 🎉" if done else f"오늘 {fmt.minutes(goal - today)} 더 읽으면 목표 달성", 15, "semibold"),
                d.caption(f"오늘 {fmt.minutes(today)} / {fmt.minutes(goal)} · 올해 {stats.get('books_done_year', 0)}/{yearly}권"),
            ], spacing=4, expand=True),
            ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=d.p.muted),
        ], spacing=16), padding=18, radius=24, on_click=lambda e: self.app.go_tab(4))

    def _activity_row(self, a: dict) -> ft.Control:
        d = self.d
        from saipr.views.together import activity_text

        return ft.Row([
            w.avatar(d, a.get("user"), 32),
            ft.Column([d.text(activity_text(a), 14, max_lines=2), d.caption(fmt.ago(a.get("created_at")))], spacing=2, expand=True, tight=True),
        ], spacing=12)

    def _room_card(self, r: dict) -> ft.Control:
        d = self.d
        members = r.get("members", [])
        me = (self.app.user or {}).get("id")
        friends = [m for m in members if m.get("user_id") != me]
        lead = max(friends, key=lambda m: m.get("progress_pct", 0), default=None)
        line = f"{lead['nickname']}님이 {lead['progress_pct']}%까지 읽었어요" if lead and lead.get("progress_pct") else (
            "친구를 초대해서 같이 읽어요" if not friends else f"{friends[0]['nickname']}님과 함께 읽는 중")
        from saipr.views.room import RoomScreen

        return d.card(ft.Column([
            ft.Row([
                ft.Column([d.text(r["name"], 16, "bold", max_lines=1),
                           d.caption(f"{'동시' if r.get('mode') == 'sync' else '비동기'} · {r.get('book_title', '')}", size=12, max_lines=1)],
                          spacing=2, expand=True),
                w.avatars(d, [{"id": m["user_id"], "nickname": m["nickname"], "avatar_color": m.get("avatar_color")} for m in members], 28),
            ]),
            d.text(line, 13),
        ], spacing=8), padding=ft.Padding.symmetric(horizontal=18, vertical=14), radius=22,
            on_click=lambda e: self.app.push(RoomScreen(self.app, f"/room/{r['id']}", room_id=r["id"])))

    def _battle_card(self, b: dict) -> ft.Control:
        d = self.d
        me = (self.app.user or {}).get("id")
        a, bb = b["team_a"], b["team_b"]
        mine, theirs = (a, bb) if any(m.get("user_id") == me for m in a.get("members", [])) else (bb, a)
        gap = round(mine["average"] - theirs["average"], 1)
        line = f"우리 팀이 {gap:g}청크 앞서는 중" if gap > 0 else (f"우리 팀이 {-gap:g}청크 뒤지는 중" if gap < 0 else "막상막하예요")
        from saipr.views.together import BattleScreen

        return d.card(ft.Column([
            ft.Row([ft.Column([d.text(f"{mine['name']} vs {theirs['name']}", 16, "bold", max_lines=1),
                               d.caption(f"{'페이지 레이스' if b['type'] == 'page_race' else '한줄평 배틀'} · {b.get('book_title', '')} · {fmt.time_left(b.get('ends_at'))}", size=12, max_lines=1)],
                              spacing=2, expand=True),
                    ft.Icon(ft.Icons.EMOJI_EVENTS_OUTLINED, color=d.p.muted)]),
            d.text(line, 13),
        ], spacing=8), padding=ft.Padding.symmetric(horizontal=18, vertical=14), radius=22,
            on_click=lambda e: self.app.push(BattleScreen(self.app, f"/battle/{b['id']}", battle_id=b["id"])))

    def _open_together(self, section: str) -> None:
        self.app.go_tab(3)
        top = self.app.stack[0]
        if hasattr(top, "section"):
            top.section = section
            top.refresh()
