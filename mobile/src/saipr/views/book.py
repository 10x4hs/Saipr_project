"""책 상세 — 표지 · 작품/작가 소개(위키백과) · 함께 읽는 친구 · 읽기 · 서재 · 방 만들기 · 진행률 기록."""

from __future__ import annotations

import flet as ft

from saipr.app import gather_safe
from saipr.core.api import ApiError, Offline
from saipr.ui import widgets as w
from saipr.views.base import Screen

SHELVES = [("want", "읽고 싶은"), ("reading", "읽는 중"), ("done", "완독")]


class BookScreen(Screen):
    title = ""

    def __init__(self, app, route, book_id: int, preview: dict | None = None):
        super().__init__(app, route)
        self.book_id = book_id
        self.preview = preview or {"id": book_id, "title": ""}
        self.title = self.preview.get("title", "")
        self.expanded = False

    def stale(self):
        return True  # 리더에서 돌아오면 진행률이 바뀌어 있다

    async def load(self):
        info, rooms = await gather_safe(self.api.get(f"/books/{self.book_id}/info"), self.api.get("/rooms"))
        if info is None:
            info = await self.api.get(f"/books/{self.book_id}")  # 정보 API가 없을 때 기본 정보라도
        self.data = {"book": info, "rooms": [r for r in (rooms or []) if r.get("book_id") == self.book_id]}
        self.title = info.get("title", "")

    def skeleton(self):
        return [self._hero(self.preview), w.skeleton(self.d, 3)]

    def _hero(self, b: dict) -> ft.Control:
        d = self.d
        return ft.Column([
            ft.Container(w.cover(d, b, 150, hero=f"cover-{b['id']}"), alignment=ft.Alignment.CENTER, padding=ft.Padding.only(top=8)),
            d.text(b.get("title", ""), 26, "bold", align=ft.TextAlign.CENTER),
            d.text(b.get("author") or " ", 15, muted=True, align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8)

    def content(self):
        d, b = self.d, self.data["book"]
        entry = b.get("my_entry")
        pct = (entry or {}).get("progress_pct", 0)
        out: list[ft.Control] = [self._hero(b)]
        chips = [w.pill(d, b["genre"])] if b.get("genre") else []
        chips.append(w.pill(d, "전문 읽기" if b.get("has_fulltext") else "진행률 기록", icon=ft.Icons.MENU_BOOK if b.get("has_fulltext") else ft.Icons.TIMELINE))
        if b.get("readers"):
            chips.append(w.pill(d, f"{b['readers']}명이 읽는 중", icon=ft.Icons.PEOPLE_OUTLINE))
        if b.get("total_chars"):
            chips.append(w.pill(d, f"약 {max(1, round(b['total_chars'] / 500))}분", icon=ft.Icons.SCHEDULE))
        out.append(ft.Row(chips, spacing=8, wrap=True, alignment=ft.MainAxisAlignment.CENTER))

        # 주요 행동
        primary_label = ("이어 읽기" if pct else "읽기 시작") if b.get("has_fulltext") else "진행률 기록"
        out.append(ft.Column([
            d.button(primary_label, lambda e: self.primary(), icon=ft.Icons.AUTO_STORIES if b.get("has_fulltext") else ft.Icons.EDIT_NOTE, key="primary"),
            ft.Row([d.button("방 만들기", lambda e: self.create_room_sheet(), icon=ft.Icons.GROUP_ADD_OUTLINED, kind="secondary", expand=True),
                    d.button("공유", lambda e: self.app.run(self.share()), icon=ft.Icons.IOS_SHARE, kind="secondary", expand=True)], spacing=10),
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH))

        # 내 진행률 · 서재
        out.append(d.card(ft.Column([
            ft.Row([d.text("내 진행률", 15, "semibold"), d.text(f"{pct}%", 15, "bold")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            d.progress(pct / 100),
            d.segmented(SHELVES, (entry or {}).get("shelf") or "", lambda s: self.app.run(self.set_shelf(s))),
        ], spacing=12), padding=18))

        friends = b.get("friends_reading") or []
        if friends:
            out.append(d.card(ft.Row([w.avatars(d, friends, 30, 5),
                                      d.text(f"{friends[0]['nickname']}님{f' 외 {len(friends) - 1}명' if len(friends) > 1 else ''}이 읽고 있어요", 14, expand=True)],
                                     spacing=12), padding=16, radius=22))

        if b.get("description"):
            desc = b["description"]
            short = desc if self.expanded or len(desc) < 160 else desc[:160].rstrip() + "…"
            out.append(d.section("작품 소개"))
            out.append(d.card(ft.Column([
                d.text(short, 15, height=1.6),
                *([ft.TextButton(content=d.text("더 보기", 13, "medium"), on_click=lambda e: self.expand())] if short != desc else []),
                *([d.caption("출처: 위키백과 (CC BY-SA)")] if b.get("wiki_url") else []),
            ], spacing=8), padding=18))
        if b.get("author_bio"):
            out.append(d.section(f"작가 · {b.get('author') or ''}"))
            out.append(d.card(d.text(b["author_bio"], 14, muted=False, height=1.6), padding=18))

        if self.data["rooms"]:
            from saipr.views.room import RoomScreen

            out.append(d.section("이 책의 내 읽기방"))
            for r in self.data["rooms"]:
                out.append(d.card(ft.Row([d.text(r["name"], 15, "semibold", expand=True), w.avatars(d, [{"id": m["user_id"], "nickname": m["nickname"]} for m in r["members"]], 26)]),
                                  padding=16, radius=20, on_click=lambda e, r=r: self.app.push(RoomScreen(self.app, f"/room/{r['id']}", room_id=r["id"]))))
        return out

    def expand(self):
        self.expanded = True
        self.refresh()

    def primary(self) -> None:
        b = self.data["book"]
        if b.get("has_fulltext"):
            from saipr.views.reader import ReaderScreen

            self.app.push(ReaderScreen(self.app, f"/read/{self.book_id}", book_id=self.book_id))
        else:
            self.progress_sheet()

    async def set_shelf(self, shelf: str) -> None:
        r = await self.app.guard(self.api.put(f"/library/{self.book_id}", {"shelf": shelf}))
        if r:
            self.app.haptic("light")
            self.app.toast({"want": "읽고 싶은 책에 담았어요", "reading": "읽는 중으로 옮겼어요", "done": "완독! 수고했어요 📚"}[shelf])
            await self.reload()

    async def share(self) -> None:
        b = self.data["book"]
        await self.app.share_text(f"「{b['title']}」 {b.get('author') or ''} — 함께읽기에서 같이 읽어요!")

    def progress_sheet(self) -> None:
        d = self.d
        entry = self.data["book"].get("my_entry") or {}
        slider = ft.Slider(min=0, max=100, divisions=100, value=entry.get("progress_pct", 0), label="{value}%")

        async def save(e):
            r = await self.app.guard(self.api.put(f"/library/{self.book_id}/progress", {"progress_pct": int(slider.value)}), ok="기록했어요")
            if r:
                self.app.close_dialog()
                await self.reload()

        self.app.sheet(ft.Column([
            ft.Text("어디까지 읽었나요?", size=20, font_family="Pretendard Bold"),
            ft.Text("시판 도서는 진행률을 직접 기록해요. 레이스 점수에는 들어가지 않아요.", size=13, font_family="Pretendard", color="#6c6c70"),
            slider,
            ft.Button(content=ft.Text("기록", font_family="Pretendard SemiBold"), on_click=save),
        ], spacing=12, tight=True))
        _ = d

    def create_room_sheet(self) -> None:
        name = ft.TextField(label="방 이름", value=f"{self.data['book']['title']} 같이 읽기", max_length=80, autofocus=True)
        mode = ft.SegmentedButton(selected=["async"], segments=[ft.Segment(value="async", label=ft.Text("각자 편할 때")), ft.Segment(value="sync", label=ft.Text("지금 같이"))])

        async def create(e):
            try:
                room = await self.api.post("/rooms", {"book_id": self.book_id, "name": name.value or "", "mode": list(mode.selected)[0]})
            except (ApiError, Offline) as err:
                self.app.toast(err.message)
                return
            self.app.close_dialog()
            self.app.haptic("medium")
            from saipr.views.room import RoomScreen

            self.app.push(RoomScreen(self.app, f"/room/{room['id']}", room_id=room["id"], fresh=True))

        self.app.sheet(ft.Column([
            ft.Text("새 읽기방", size=20, font_family="Pretendard Bold"),
            ft.Text("방을 만들면 초대 코드가 생겨요. 친구에게 보내 같이 읽어요.", size=13, font_family="Pretendard", color="#6c6c70"),
            name, mode,
            ft.Button(content=ft.Text("방 만들기", font_family="Pretendard SemiBold"), on_click=create),
        ], spacing=12, tight=True))
