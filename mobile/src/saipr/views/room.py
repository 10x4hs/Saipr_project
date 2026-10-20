"""읽기방 — 멤버 진행률 · 채팅 · 최근 반응 · 초대.

실시간: 방 채널에서 progress.updated · member.joined · reaction.created · message.created를 받는다.
"""

from __future__ import annotations

import flet as ft

from saipr.core import fmt
from saipr.ui import widgets as w
from saipr.ui.theme import alpha
from saipr.views.base import Screen


class RoomScreen(Screen):
    title = "읽기방"

    def __init__(self, app, route, room_id: int, fresh: bool = False):
        super().__init__(app, route)
        self.room_id = room_id
        self.section = "chat"
        self.messages: list[dict] = []
        self.channel = None
        self.chat_list: ft.ListView | None = None
        self.input: ft.TextField | None = None
        self.tabs: ft.Container | None = None
        if fresh:
            self.app.toast("방을 만들었어요. 초대 코드를 친구에게 보내 주세요!")

    def stale(self):
        return self.data is None

    async def load(self):
        room = await self.api.get(f"/rooms/{self.room_id}")  # 방이 없으면 여기서 오류 화면
        messages = None
        try:
            messages = await self.api.get(f"/rooms/{self.room_id}/messages", limit=50)
        except Exception:
            pass
        self.messages = messages or []
        try:
            feed = await self.api.get(f"/books/{room['book_id']}/reactions", room_id=self.room_id)
        except Exception:
            feed = None
        self.data = {"room": room, "feed": feed}
        self.title = room["name"]

    async def on_show(self):
        await super().on_show()
        if self.data and self.channel is None:
            self.channel = self.app.realtime.channel(f"/ws/rooms/{self.room_id}")
            self.channel.subscribe(self.on_event)

    def on_hide(self):
        if self.channel:
            self.channel.unsubscribe(self.on_event)
            self.channel = None

    def actions(self):
        return [self.d.icon_button(ft.Icons.PERSON_ADD_ALT_1_ROUNDED, lambda e: self.app.run(self.invite()), "친구 초대", key="invite")]

    def content(self):
        d = self.d
        room = self.data["room"]
        me = (self.app.user or {}).get("id")
        out: list[ft.Control] = [ft.Column([
            d.caption(f"{room.get('book_title', '')} · {'동시' if room.get('mode') == 'sync' else '비동기'} 모드"),
            d.text(room["name"], 26, "bold"),
        ], spacing=2)]
        out.append(ft.Container(
            ft.Row([ft.Icon(ft.Icons.CHAT_BUBBLE_ROUNDED, size=18, color="#191919"), d.text("카카오톡으로 친구 초대", 15, "semibold", color="#191919")],
                   spacing=8, alignment=ft.MainAxisAlignment.CENTER),
            padding=14, border_radius=9999 if d.is_glass else 14, bgcolor="#FEE500", on_click=lambda e: self.app.run(self.invite()), key="kakao"))
        members = []
        for m in room["members"]:
            mine = m["user_id"] == me
            members.append(ft.Row([
                w.avatar(d, {"id": m["user_id"], "nickname": m["nickname"], "avatar_color": m.get("avatar_color")}, 34, me=mine),
                ft.Column([
                    ft.Row([d.text("나" if mine else m["nickname"], 14, "bold" if mine else "regular"),
                            d.caption(f"{m['progress_pct']}%" + (" · 방장" if m.get("is_owner") else ""), size=12)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    d.progress(m["progress_pct"] / 100, soft=not mine),
                ], spacing=6, expand=True),
            ], spacing=12, key=f"m-{m['user_id']}"))
        out.append(d.card(ft.Column([d.text("멤버 진행률", 16, "bold"), *members], spacing=14), padding=20))
        out.append(d.button("함께 읽기", lambda e: self.read(), icon=ft.Icons.AUTO_STORIES, key="read"))
        self.tabs = ft.Container(self._tabs())
        out.append(self.tabs)
        out.append(self._chat() if self.section == "chat" else self._reactions())
        return out

    def _tabs(self) -> ft.Control:
        return self.d.segmented([("chat", f"채팅 {len(self.messages)}"), ("reactions", "최근 반응")], self.section, self.set_section)

    def set_section(self, s: str) -> None:
        self.section = s
        self.refresh()

    def _bubble(self, m: dict) -> ft.Control:
        d = self.d
        mine = (m.get("user") or {}).get("id") == (self.app.user or {}).get("id")
        bubble_bg = (alpha("#ffffff", 0.92) if d.is_glass else d.p.accent) if mine else (alpha("#ffffff", 0.16) if d.is_glass else d.p.surface)
        fg = ("#1d1d1f" if d.is_glass else d.p.on_accent) if mine else d.p.fg
        bubble = ft.Container(ft.Text(m["body"], size=15, font_family="Pretendard", color=fg, selectable=True),
                              padding=ft.Padding.symmetric(horizontal=14, vertical=10), bgcolor=bubble_bg,
                              border_radius=ft.BorderRadius.only(top_left=18, top_right=18, bottom_left=4 if not mine else 18, bottom_right=4 if mine else 18))
        meta = d.text(fmt.clock(m.get("created_at")), 11, muted=True)
        if mine:
            return ft.Row([meta, ft.Container(bubble, width=None)], alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.END, spacing=6)
        return ft.Row([w.avatar(d, m.get("user"), 28), ft.Column([d.text((m.get("user") or {}).get("nickname", ""), 12, muted=True), bubble], spacing=3, tight=True), meta],
                      vertical_alignment=ft.CrossAxisAlignment.END, spacing=8)

    def _chat(self) -> ft.Control:
        d = self.d
        self.chat_list = ft.Column([self._bubble(m) for m in self.messages] or [d.caption("첫 인사를 남겨 보세요 👋")], spacing=10)
        self.input = d.field("", hint="메시지 보내기", on_submit=lambda e: self.app.run(self.send()), max_length=500, key="chat-input")
        return d.card(ft.Column([
            self.chat_list,
            ft.Row([ft.Container(self.input, expand=True), d.icon_button(ft.Icons.SEND_ROUNDED, lambda e: self.app.run(self.send()), "보내기", key="chat-send")], spacing=6),
        ], spacing=14), padding=16)

    def _reactions(self) -> ft.Control:
        d = self.d
        feed = self.data.get("feed") or {}
        rows: list[ft.Control] = [d.text(f"{r['nickname']} · {r['chunk_index'] + 1}쪽 · “{r['body']}”", 14)
                                  for r in list(reversed(feed.get("visible", [])))[:8]]
        if feed.get("locked_total"):
            rows.append(w.pill(d, f"잠김 · 아직 읽지 않은 위치에 반응 {feed['locked_total']}개", icon=ft.Icons.LOCK_OUTLINE))
        return d.card(ft.Column(rows or [d.caption("아직 반응이 없어요")], spacing=10), padding=18)

    async def send(self) -> None:
        body = (self.input.value or "").strip()
        if not body:
            return
        self.input.value = ""
        self.input.update()
        m = await self.app.guard(self.api.post(f"/rooms/{self.room_id}/messages", {"body": body}))
        if m:
            self.app.haptic("light")
            self._add_message(m)

    def _add_message(self, m: dict) -> None:
        if any(x.get("id") == m.get("id") for x in self.messages):
            return
        self.messages.append(m)
        if self.section == "chat" and self.chat_list is not None:
            if len(self.messages) == 1:
                self.chat_list.controls.clear()
            self.chat_list.controls.append(self._bubble(m))
            if w.mounted(self.chat_list):
                self.chat_list.update()
        if self.tabs is not None and w.mounted(self.tabs):
            self.tabs.content = self._tabs()
            self.tabs.update()

    async def on_event(self, ev: dict) -> None:
        t, data = ev.get("type"), ev.get("data") or {}
        me = (self.app.user or {}).get("id")
        if t == "message.created":
            if (data.get("user") or {}).get("id") != me:
                self.app.haptic("light")
            self._add_message(data)
        elif t in ("progress.updated", "member.joined", "member.left"):
            if data.get("user_id") != me and t == "member.joined":
                self.app.toast(f"{data.get('nickname')}님이 들어왔어요")
            self._reload_keep_draft()
        elif t == "reaction.created":
            self._reload_keep_draft()

    def _reload_keep_draft(self) -> None:
        """다시 그려도 쓰던 메시지는 남긴다."""
        draft = self.input.value if self.input is not None else ""

        async def go():
            await self.reload()
            if draft and self.input is not None and not self.input.value:
                self.input.value = draft
                if w.mounted(self.input):
                    self.input.update()

        self.app.run(go())

    def read(self) -> None:
        room = self.data["room"]
        if room.get("has_fulltext", True):
            from saipr.views.reader import ReaderScreen

            self.app.push(ReaderScreen(self.app, f"/read/{room['book_id']}", book_id=room["book_id"], room_id=self.room_id))
        else:
            from saipr.views.book import BookScreen

            self.app.push(BookScreen(self.app, f"/book/{room['book_id']}", book_id=room["book_id"]))

    async def invite(self) -> None:
        room = self.data["room"]
        code = room.get("invite_code") or ""
        link = f"{self.api.base_url}/r/{code}"
        await self.app.share_text(f"「{room.get('book_title', '')}」 같이 읽어요!\n함께읽기 앱 → 함께 → 읽기방 → 초대 코드: {code}\n{link}")
