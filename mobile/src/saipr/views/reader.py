"""리더 — 쪽 넘김(청크 = 쪽), 종이 시트, 문단 반응, 밑줄·메모, 친구 위치, 스포일러 잠금.

측정: 지금 보이는 쪽에만 시간을 쌓고, 앱이 백그라운드로 가면 멈춘다(DwellTracker). 10초마다 서버로 보내고,
보내지 못한 기록은 기기에 모았다가 연결되면 보낸다. 판정은 서버가 한다.
"""

from __future__ import annotations

import asyncio
import re

import flet as ft

from saipr.app import gather_safe
from saipr.core import fmt
from saipr.core.api import ApiError, Offline
from saipr.core.reading import MILESTONES, DwellTracker, EventQueue, SpeedModel, crossed_milestone
from saipr.core.sync import SessionExpired
from saipr.ui import widgets as w
from saipr.ui.theme import HIGHLIGHT_COLORS, alpha
from saipr.views.base import Screen

EMOJIS = ("❤️", "😂", "😮", "😢", "👍")
PAPERS = {  # 배경 · 글자 · 흐린 글자
    "paper": ("#fcf9f2", "#2a251f", "#a0937f"),
    "sepia": ("#f1e7d0", "#3b2f22", "#9a8466"),
    "dark": ("#1c1b19", "#d8d2c4", "#8c857a"),
}
SIZES = (15, 16.5, 18.5, 21)
SPACINGS = ((1.7, 6), (1.9, 12), (2.15, 20))
SENTENCE = re.compile(r".*?(?:[.!?…。]+[\"”」']?\s+|$)", re.S)


def sentences(text: str) -> list[str]:
    parts = [p for p in SENTENCE.findall(text) if p]
    return parts or [text]


class ReaderScreen(Screen):
    padded = False

    def __init__(self, app, route, book_id: int, room_id: int | None = None):
        super().__init__(app, route)
        self.book_id, self.room_id = book_id, room_id
        self.book: dict = {}
        self.entry: dict = {}
        self.total = 0
        self.index = 0
        self.pages: dict[int, dict] = {}  # 받아 둔 쪽: {paragraphs, chars, min_dwell_ms}
        self.page_boxes: list[ft.Container] = []
        self.tracker = DwellTracker()
        self.queue = EventQueue()
        self.speed = SpeedModel()
        self.pref = {"size": 1, "spacing": 1, "paper": "dark" if app.design.dark else "paper", "font": "serif"}
        self.reactions: dict[str, list] = {}
        self.locked_total = 0
        self.my_highlights: list[dict] = []
        self.friend_highlights: list[dict] = []
        self.friends_at: dict[int, dict] = {}
        self.room: dict | None = None
        self.members: list[dict] = []
        self._loop_task: asyncio.Task | None = None
        self.channel = None
        self.pager: ft.PageView | None = None
        self.top_pct: ft.Text | None = None
        self.top_bar: ft.ProgressBar | None = None
        self.eta: ft.Text | None = None
        self.guard_pill: ft.Container | None = None
        self.chrome = True
        # 쪽 넘김(PageView)은 스크롤 목록 안에 둘 수 없어서 본문을 화면을 채우는 Column으로 바꾼다
        self.body = ft.Column(expand=True, spacing=0, controls=[])

    # ── 불러오기 ───────────────────────────────────
    def stale(self):
        return self.data is None

    async def load(self):
        self.pref.update(await self.app.store.get("reader", {}) or {})
        self.queue = await self.app.sync.load(self.book_id)
        self.speed.cpm = await self.app.store.get("cpm", self.speed.cpm)
        try:
            info, library, rooms = await gather_safe(
                self.api.get(f"/books/{self.book_id}/info"), self.api.get("/library"), self.api.get("/rooms"))
        except Offline:
            info, library, rooms = await self.app.store.get(f"book.{self.book_id}"), None, None
            if info is None:
                raise
            self.app.toast("오프라인이에요. 받아 둔 쪽은 읽을 수 있어요")
        if info is None:
            info = await self.api.get(f"/books/{self.book_id}")
        await self.app.store.set(f"book.{self.book_id}", info)
        self.book = info
        self.title = info.get("title", "")
        self.total = int(info.get("total_chunks") or 0)
        entry = next((e for e in (library or []) if e.get("book_id") == self.book_id), None) or info.get("my_entry") or {}
        self.entry = entry
        rooms_here = [r for r in (rooms or []) if r.get("book_id") == self.book_id]
        self.room = next((r for r in rooms_here if r["id"] == self.room_id), rooms_here[0] if rooms_here else None)
        me = (self.app.user or {}).get("id")
        self.members = [m for m in (self.room or {}).get("members", []) if m.get("user_id") != me]
        self.friends_at = {m["user_id"]: {"nickname": m["nickname"], "chunk": min(self.total - 1, m.get("verified_chunk", -1) + 1)} for m in self.members}
        verified = entry.get("verified_chunk", -1)
        self.index = max(0, min(self.total - 1, verified + 1)) if self.total else 0
        self.data = True
        await self._ensure_pages(self.index)
        self.app.run(self._load_social())

    async def _fetch_page(self, i: int) -> dict | None:
        if i in self.pages or not (0 <= i < self.total):
            return self.pages.get(i)
        cached = await self.app.store.chunk(self.book_id, i)
        try:
            data = await self.api.get(f"/books/{self.book_id}/chunks/{i}")
            page = {"paragraphs": [p for p in data["text"].split("\n\n") if p.strip()], "min_dwell_ms": data.get("min_dwell_ms", 0)}
            page["chars"] = sum(len(p.replace(" ", "")) for p in page["paragraphs"])
            await self.app.store.save_chunk(self.book_id, i, page)  # 비행기 모드에서도 다시 읽히게
        except Offline:
            if not cached:
                return None
            page = cached
        self.pages[i] = page
        return page

    async def _ensure_pages(self, center: int) -> None:
        await asyncio.gather(*(self._fetch_page(i) for i in (center, center + 1, center - 1)))

    async def _load_social(self) -> None:
        q = {"room_id": self.room["id"]} if self.room else {}
        try:
            feed, mine, friends = await gather_safe(
                self.api.get(f"/books/{self.book_id}/reactions", **q),
                self.api.get("/me/highlights", book_id=self.book_id),
                self.api.get(f"/books/{self.book_id}/highlights", scope="friends"),
            )
        except (ApiError, Offline):
            return  # 오프라인: 반응 없이 본문만
        self.reactions = {}
        for r in (feed or {}).get("visible", []):
            self.reactions.setdefault(f"{r['chunk_index']}:{r['anchor']}", []).append(r)
        self.locked_total = (feed or {}).get("locked_total", 0)
        self.my_highlights = mine or []
        self.friend_highlights = (friends or {}).get("visible", []) if isinstance(friends, dict) else (friends or [])
        self._refresh_pages()
        self._refresh_guard()

    # ── 화면 ───────────────────────────────────────
    def header(self):
        return None

    def skeleton(self):
        return [ft.Container(ft.ProgressRing(), alignment=ft.Alignment.CENTER, expand=True, padding=120)]

    def _colors(self):
        return PAPERS[self.pref.get("paper", "paper")]

    def content(self):
        d = self.d
        bg, ink, faint = self._colors()
        self.page_boxes = [ft.Container(expand=True) for _ in range(self.total)]
        for i in range(self.total):
            self.page_boxes[i].content = self._page(i)
        self.pager = ft.PageView(controls=self.page_boxes, selected_index=self.index, expand=True,
                                 on_change=lambda e: self.app.run(self.on_page(int(e.data) if str(e.data).isdigit() else e.control.selected_index)))
        pct = self.entry.get("progress_pct", 0)
        self.top_pct = d.text(f"{pct}%", 13, "semibold")
        self.top_bar = d.progress(pct / 100, 3)
        self.eta = d.text("", 11, muted=True)
        glass = d.is_glass
        top = ft.Container(
            ft.Column([
                ft.Row([
                    ft.IconButton(ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED, icon_size=18, icon_color=d.p.fg, on_click=lambda e: self.app.pop(), key="back"),
                    ft.Container(d.text(self.book.get("title", ""), 16, "semibold", max_lines=1), expand=True),
                    *([w.avatars(d, [{"id": m["user_id"], "nickname": m["nickname"]} for m in self.members], 24, 3)] if self.members else []),
                    ft.IconButton(ft.Icons.TEXT_FIELDS_ROUNDED, icon_size=20, icon_color=d.p.fg, tooltip="읽기 설정", on_click=lambda e: self.settings_sheet(), key="settings"),
                    self.top_pct,
                ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.top_bar,
                self.eta,
            ], spacing=6, tight=True),
            padding=ft.Padding.only(left=6, right=16, top=6, bottom=10),
            margin=ft.Margin.only(left=12, right=12, top=6),
            border_radius=24 if glass else 0,
            blur=ft.Blur(30, 30) if glass else None,
            bgcolor=alpha("#ffffff", 0.18) if glass else d.p.bg,
            border=ft.Border.all(1, alpha("#ffffff", 0.38)) if glass else None,
        )
        sheet = ft.Container(
            self.pager, expand=True, bgcolor=alpha(bg, 0.9) if glass else bg,
            border_radius=32 if glass else 0, margin=ft.Margin.only(left=10, right=10, top=10, bottom=10) if glass else None,
            blur=ft.Blur(20, 20) if glass else None,
            shadow=ft.BoxShadow(blur_radius=30, offset=ft.Offset(0, 12), color=alpha("#000000", 0.18)) if glass else None,
        )
        self._update_eta()
        return [ft.Column([top, sheet], spacing=0, expand=True)]

    def _render_body(self):
        if self.error and self.data is None:
            return super()._render_body()
        if self.data is None:
            return self.skeleton()
        return self.content()

    def refresh(self) -> None:
        # 리더는 목록이 아니라 화면 전체를 채운다 — ListView 대신 Column 하나
        self.body.controls = self._render_body()
        if w.mounted(self.view):
            self.body.update()

    def overlay(self):
        self.guard_pill = ft.Container(
            w.pill(self.d, "", dark=True), bottom=34, left=0, right=0, alignment=ft.Alignment.CENTER, visible=False,
        )
        return [self.guard_pill]

    def _refresh_guard(self) -> None:
        if not self.guard_pill:
            return
        self.guard_pill.visible = bool(self.locked_total) and bool((self.app.user or {}).get("spoiler_guard", True))
        self.guard_pill.content = w.pill(self.d, f"잠김 · 앞에서 {self.locked_total}개의 반응이 기다리고 있어요", dark=True, icon=ft.Icons.LOCK_OUTLINE)
        if w.mounted(self.guard_pill):
            self.guard_pill.update()

    def _page(self, i: int) -> ft.Control:
        bg, ink, faint = self._colors()
        page = self.pages.get(i)
        size = SIZES[int(self.pref.get("size", 1))]
        lh, gap = SPACINGS[int(self.pref.get("spacing", 1))]
        font = "Gowun Batang" if self.pref.get("font", "serif") == "serif" else "Pretendard"
        if page is None:
            return ft.Container(ft.Column([ft.ProgressRing(color=faint), ft.Text("쪽을 불러오는 중…", color=faint, font_family="Pretendard")],
                                          horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
                                alignment=ft.Alignment.CENTER, expand=True)
        items: list[ft.Control] = []
        if i == 0:
            run = " ".join(self.book.get("title", "")) + " · " + " ".join(self.book.get("author") or "")
            items.append(ft.Container(ft.Text(run, size=11, color=faint, font_family="Pretendard", text_align=ft.TextAlign.CENTER),
                                      padding=ft.Padding.only(bottom=14), border=ft.Border.only(bottom=ft.BorderSide(1, alpha(faint, 0.3))),
                                      alignment=ft.Alignment.CENTER))
        for a, para in enumerate(page["paragraphs"]):
            items.append(self._paragraph(i, a, para, size, lh, ink, font))
            items.extend(self._notes(i, a, ink, faint))
        here = [f["nickname"] for uid, f in self.friends_at.items() if f["chunk"] == i]
        if here:
            items.append(ft.Row([ft.Container(width=7, height=7, bgcolor="#0066cc", border_radius=7),
                                 ft.Text(f"{', '.join(here[:2])}님{f' 외 {len(here) - 2}명' if len(here) > 2 else ''}이 이 쪽을 함께 읽고 있어요",
                                         size=12, color=faint, font_family="Pretendard")], spacing=8))
        done = i <= self.entry.get("verified_chunk", -1)
        items.append(ft.Container(ft.Row([ft.Text(f"{i + 1}  /  {self.total}", size=12, color=faint, font_family="Gowun Batang"),
                                          *([ft.Text("✓ 읽음", size=12, color="#3d8b5a", font_family="Pretendard Medium")] if done else [])],
                                         alignment=ft.MainAxisAlignment.CENTER, spacing=8), padding=ft.Padding.only(top=18, bottom=40)))
        return ft.ListView(items, spacing=gap, padding=ft.Padding.only(left=28, right=28, top=22, bottom=20), expand=True)

    def _paragraph(self, i: int, a: int, text: str, size: float, lh: float, ink: str, font: str) -> ft.Control:
        marks = [(h["quote"], HIGHLIGHT_COLORS.get(h.get("color", "yellow"), "#FFD95A")) for h in self.my_highlights
                 if h.get("chunk_index") == i and h.get("anchor") == a]
        style = ft.TextStyle(size=size, color=ink, font_family=font, height=lh)
        spans: list[ft.TextSpan] = []
        rest = text
        for quote, color in marks:  # 내 밑줄: 형광펜처럼 배경색
            pos = rest.find(quote)
            if pos < 0:
                continue
            spans += [ft.TextSpan(fmt.keep_all(rest[:pos]), style),
                      ft.TextSpan(fmt.keep_all(quote), ft.TextStyle(size=size, color=ink, font_family=font, height=lh, bgcolor=alpha(color, 0.55)))]
            rest = rest[pos + len(quote):]
        spans.append(ft.TextSpan(fmt.keep_all(rest), style))
        para = ft.Text(spans=spans, style=style, text_align=ft.TextAlign.LEFT)
        return ft.GestureDetector(
            content=ft.Container(para, border_radius=8, padding=ft.Padding.symmetric(vertical=2)),
            on_tap=lambda e: self.reaction_sheet(i, a),
            on_long_press_start=lambda e: self.highlight_sheet(i, a, text),
        )

    def _notes(self, i: int, a: int, ink: str, faint: str) -> list[ft.Control]:
        d = self.d
        out: list[ft.Control] = []
        rx = self.reactions.get(f"{i}:{a}", [])
        comments = [r for r in rx if r["kind"] == "comment"]
        emojis = [r for r in rx if r["kind"] == "emoji"]
        for r in comments[-2:]:
            out.append(ft.Container(ft.Row([
                w.avatar(d, {"id": r["user_id"], "nickname": r["nickname"]}, 20),
                ft.Text(spans=[ft.TextSpan(r["body"] + " ", ft.TextStyle(color=alpha(ink, 0.8))),
                               ft.TextSpan("· " + r["nickname"], ft.TextStyle(color=faint))],
                        size=13, font_family="Gowun Batang", expand=True),
            ], spacing=9, vertical_alignment=ft.CrossAxisAlignment.START),
                padding=ft.Padding.only(left=12), border=ft.Border.only(left=ft.BorderSide(2, "#d9c6a0")),
                on_click=lambda e, i=i, a=a: self.reaction_sheet(i, a)))
        if emojis:
            counts: dict[str, int] = {}
            for r in emojis:
                counts[r["body"]] = counts.get(r["body"], 0) + 1
            out.append(ft.Container(ft.Text("  ".join(f"{k} {v}" for k, v in counts.items()), size=13, color=faint),
                                    padding=ft.Padding.only(left=12), on_click=lambda e, i=i, a=a: self.reaction_sheet(i, a)))
        for h in [h for h in self.friend_highlights if h.get("chunk_index") == i and h.get("anchor") == a][:2]:
            who = (h.get("user") or {}).get("nickname", "")
            out.append(ft.Container(ft.Text(f"✎ {who}님의 밑줄 — “{h['quote'][:40]}”" + (f" {h['note']}" if h.get("note") else ""),
                                            size=12, color=faint, font_family="Gowun Batang"), padding=ft.Padding.only(left=12)))
        return out

    def _refresh_pages(self) -> None:
        for i, box in enumerate(self.page_boxes):
            if abs(i - self.index) <= 1:
                box.content = self._page(i)
                if w.mounted(box):
                    box.update()

    def _update_eta(self) -> None:
        if not self.eta:
            return
        page = self.pages.get(self.index)
        if not page:
            self.eta.value = ""
            return
        known = [p["chars"] for p in self.pages.values() if p.get("chars")]
        avg = sum(known) / len(known) if known else page.get("chars", 0)
        remaining = page.get("chars", 0) + avg * max(0, self.total - 1 - self.index)
        self.eta.value = self.speed.eta_text(page.get("chars", 0), int(remaining))
        if w.mounted(self.eta):
            self.eta.update()

    # ── 쪽 넘김 · 측정 ───────────────────────────────
    async def on_page(self, i: int) -> None:
        if i == self.index:
            return
        self.index = i
        self.tracker.show(i)
        self.app.haptic("selection")
        await self._ensure_pages(i)
        self._refresh_pages()
        self._update_eta()
        if self.room and self.room.get("mode") == "sync" and self.channel:
            await self.channel.send({"type": "presence", "chunk_index": i})

    async def on_show(self):
        await super().on_show()
        if self.data is None:
            return
        self.tracker.resume()
        self.tracker.show(self.index)
        try:
            await self.app.wakelock.enable()  # 읽는 동안 화면이 꺼지지 않게
        except Exception:
            pass
        if self._loop_task is None:
            self._loop_task = asyncio.ensure_future(self._loop())
        if self.room and self.channel is None:
            self.channel = self.app.realtime.channel(f"/ws/rooms/{self.room['id']}")
            self.channel.subscribe(self.on_event)

    def on_hide(self):
        self.tracker.pause()
        self.queue.push(self.tracker.drain())
        self.app.run(self.flush())
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None
        if self.channel:
            self.channel.unsubscribe(self.on_event)
            self.channel = None

        async def unlock():
            try:
                await self.app.wakelock.disable()
            except Exception:
                pass

        self.app.run(unlock())

    async def on_lifecycle(self, state) -> None:
        if state in (ft.AppLifecycleState.PAUSE, ft.AppLifecycleState.HIDE, ft.AppLifecycleState.INACTIVE):
            self.tracker.pause()
            self.queue.push(self.tracker.drain())
            await self.flush()
        elif state in (ft.AppLifecycleState.RESUME, ft.AppLifecycleState.SHOW):
            self.tracker.resume()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            self.tracker.tick()
            self.queue.push(self.tracker.drain())
            await self.flush()

    async def flush(self) -> None:
        try:
            r = await self.app.sync.send(self.book_id, self.queue)
        except SessionExpired:
            self.app.run(self.app.session_expired())  # 기록은 기기에 남는다 — 다시 로그인하면 보낸다
            return
        if r:
            await self._on_progress(r)

    async def _on_progress(self, r: dict) -> None:
        before = self.entry.get("progress_pct", 0)
        self.entry["verified_chunk"] = r["verified_chunk"]
        self.entry["progress_pct"] = r["progress_pct"]
        for i in r.get("newly_verified", []):
            page = self.pages.get(i)
            if page:
                self.speed.learn(page.get("chars", 0), self.tracker.dwell_by_chunk.get(i, 0))
        await self.app.store.set("cpm", self.speed.cpm)
        if self.top_pct:
            self.top_pct.value = f"{r['progress_pct']}%"
            self.top_bar.value = r["progress_pct"] / 100
            if w.mounted(self.top_pct):
                self.top_pct.update()
                self.top_bar.update()
        hit = crossed_milestone(before, r["progress_pct"])
        if hit:
            self.app.haptic("heavy")
            self.app.toast(MILESTONES[hit])
        elif r.get("points_awarded"):
            self.app.toast(f"+{r['points_awarded']}P · 한 쪽 읽음")
        if r.get("slow_down"):
            self.app.toast("천천히 읽어도 괜찮아요. 빠르게 넘긴 쪽은 점수에 들어가지 않아요.")
        if r.get("newly_verified"):
            await self._load_social()  # 가드가 풀린 반응
        self._refresh_pages()
        self._update_eta()

    async def on_event(self, ev: dict) -> None:
        d_ = ev.get("data") or {}
        if d_.get("user_id") == (self.app.user or {}).get("id"):
            return
        t = ev.get("type")
        if t in ("progress.updated", "member.joined"):
            self.friends_at[d_["user_id"]] = {"nickname": d_["nickname"], "chunk": min(self.total - 1, d_.get("verified_chunk", -1) + 1)}
            if t == "progress.updated":
                self.app.toast(f"{d_['nickname']}님 {d_['progress_pct']}%")
            self._refresh_pages()
        elif t == "presence.changed":
            self.friends_at[d_["user_id"]] = {"nickname": d_["nickname"], "chunk": d_["chunk_index"]}
            self._refresh_pages()
        elif t == "reaction.created":
            self.app.haptic("light")
            await self._load_social()

    # ── 시트: 반응 · 밑줄 · 설정 ─────────────────────────
    def reaction_sheet(self, i: int, a: int) -> None:
        d = self.d
        rx = self.reactions.get(f"{i}:{a}", [])
        comment = ft.TextField(hint_text="이 문단, 어땠어요?", max_length=280, expand=True, border_radius=16)

        async def send(kind: str, body: str) -> None:
            if not body.strip():
                return
            r = await self.app.guard(self.api.post(f"/books/{self.book_id}/reactions",
                                                   {"chunk_index": i, "anchor": a, "kind": kind, "body": body.strip()}))
            if r:
                self.app.haptic("medium")
                self.app.close_dialog()
                await self._load_social()

        lst = [ft.Container(ft.Column([ft.Text(r["nickname"], size=12, color="#8a8a8e", font_family="Pretendard"),
                                       ft.Text(r["body"], size=22 if r["kind"] == "emoji" else 15, font_family="Pretendard")], spacing=2),
                            padding=12, border_radius=14, bgcolor=alpha("#000000", 0.04)) for r in rx]
        self.app.sheet(ft.Column([
            ft.Text(f"{i + 1}쪽 · {a + 1}번째 문단", size=18, font_family="Pretendard Bold"),
            ft.Row([ft.Container(ft.Text(e, size=26), padding=10, border_radius=16, bgcolor=alpha("#000000", 0.05),
                                 on_click=lambda ev, e=e: self.app.run(send("emoji", e)), expand=True, alignment=ft.Alignment.CENTER) for e in EMOJIS], spacing=8),
            ft.Row([comment, ft.IconButton(ft.Icons.SEND_ROUNDED, on_click=lambda e: self.app.run(send("comment", comment.value or "")))]),
            *(lst or [ft.Text("아직 반응이 없어요. 첫 반응을 남겨 보세요.", size=13, color="#8a8a8e", font_family="Pretendard")]),
        ], spacing=12, tight=True))
        _ = d

    def highlight_sheet(self, i: int, a: int, text: str) -> None:
        self.app.haptic("medium")
        parts = sentences(text)
        chosen = {0} if len(parts) == 1 else set()
        color = {"v": "yellow"}
        visibility = {"v": "friends"}
        note = ft.TextField(hint_text="메모 (선택)", max_length=280, multiline=True, min_lines=1, max_lines=3, border_radius=16)
        chips = ft.Column(spacing=6)
        swatches = ft.Row(spacing=10)

        def draw():
            chips.controls = [ft.Container(
                ft.Text(p.strip(), size=14, font_family="Gowun Batang", color="#2a251f"),
                padding=10, border_radius=12,
                bgcolor=alpha(HIGHLIGHT_COLORS[color["v"]], 0.6) if k in chosen else alpha("#000000", 0.04),
                on_click=lambda e, k=k: toggle(k)) for k, p in enumerate(parts)]
            swatches.controls = [ft.Container(width=30, height=30, border_radius=30, bgcolor=c,
                                              border=ft.Border.all(3, "#1d1d1f") if name == color["v"] else None,
                                              on_click=lambda e, name=name: pick(name)) for name, c in HIGHLIGHT_COLORS.items()]

        def toggle(k):
            chosen.symmetric_difference_update({k})
            draw()
            chips.update()

        def pick(name):
            color["v"] = name
            draw()
            chips.update()
            swatches.update()

        async def save(e):
            if not chosen:
                self.app.toast("밑줄 그을 문장을 골라 주세요")
                return
            lo, hi = min(chosen), max(chosen)
            quote = "".join(parts[lo:hi + 1]).strip()
            r = await self.app.guard(self.api.post(f"/books/{self.book_id}/highlights", {
                "chunk_index": i, "anchor": a, "quote": quote, "note": (note.value or "").strip() or None,
                "color": color["v"], "visibility": visibility["v"]}))
            if r:
                self.app.haptic("medium")
                self.app.close_dialog()
                self.app.toast("밑줄을 그었어요 · 서재 → 밑줄에서 모아 볼 수 있어요")
                await self._load_social()

        vis = ft.CupertinoSlidingSegmentedButton(controls=[ft.Text("팔로워에게 공개", font_family="Pretendard"), ft.Text("나만 보기", font_family="Pretendard")],
                                                 selected_index=0, on_change=lambda e: visibility.update(v="friends" if int(e.control.selected_index) == 0 else "private"))
        draw()
        self.app.sheet(ft.Column([
            ft.Text("밑줄 · 메모", size=18, font_family="Pretendard Bold"),
            ft.Text("밑줄 그을 문장을 눌러 고르세요 (이어진 문장은 함께 묶여요)", size=12, color="#8a8a8e", font_family="Pretendard"),
            chips, swatches, note, vis,
            ft.Button(content=ft.Text("밑줄 긋기", font_family="Pretendard SemiBold"), on_click=save),
        ], spacing=12, tight=True))

    def settings_sheet(self) -> None:
        def seg(options, current, key):
            return ft.CupertinoSlidingSegmentedButton(
                controls=[ft.Text(o, font_family="Pretendard") for o in options], selected_index=current,
                on_change=lambda e: self.app.run(self.set_pref(key, int(e.control.selected_index))))

        papers = list(PAPERS)
        self.app.sheet(ft.Column([
            ft.Text("읽기 설정", size=18, font_family="Pretendard Bold"),
            ft.Text("글자 크기", size=12, color="#8a8a8e", font_family="Pretendard"), seg(["작게", "보통", "크게", "아주 크게"], int(self.pref["size"]), "size"),
            ft.Text("줄 간격 · 문단 간격", size=12, color="#8a8a8e", font_family="Pretendard"), seg(["촘촘", "보통", "여유"], int(self.pref["spacing"]), "spacing"),
            ft.Text("글꼴", size=12, color="#8a8a8e", font_family="Pretendard"), seg(["바탕(명조)", "고딕"], 0 if self.pref["font"] == "serif" else 1, "font"),
            ft.Text("배경", size=12, color="#8a8a8e", font_family="Pretendard"), seg(["종이", "세피아", "다크"], papers.index(self.pref["paper"]), "paper"),
            ft.Text("읽는 동안 화면이 꺼지지 않아요 · 한 번 연 쪽은 오프라인에서도 읽혀요", size=12, color="#8a8a8e", font_family="Pretendard"),
        ], spacing=10, tight=True))

    async def set_pref(self, key: str, idx: int) -> None:
        if key == "font":
            self.pref["font"] = "serif" if idx == 0 else "sans"
        elif key == "paper":
            self.pref["paper"] = list(PAPERS)[idx]
        else:
            self.pref[key] = idx
        await self.app.store.set("reader", self.pref)
        self.app.haptic("selection")
        for i, box in enumerate(self.page_boxes):
            box.content = self._page(i)
        self.body.controls = self.content()
        self.body.update()
