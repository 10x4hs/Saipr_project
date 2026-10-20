"""서재 — 읽는 중 · 읽고 싶은 · 완독 · 밑줄·메모."""

from __future__ import annotations

import flet as ft

from saipr.app import gather_safe
from saipr.core import fmt
from saipr.ui import widgets as w
from saipr.ui.theme import HIGHLIGHT_COLORS, alpha
from saipr.views.base import Screen

SECTIONS = [("reading", "읽는 중"), ("want", "읽고 싶은"), ("done", "완독"), ("highlights", "밑줄")]


class LibraryScreen(Screen):
    tab = 2
    large_title = "서재"

    def __init__(self, app, route, **params):
        super().__init__(app, route, **params)
        self.section = "reading"

    async def load(self):
        library, highlights = await gather_safe(self.api.get("/library"), self.api.get("/me/highlights"))
        self.data = {"library": library or [], "highlights": highlights or []}
        if self.section != "highlights" and not any(e["shelf"] == self.section for e in self.data["library"]):
            self.section = next((k for k, _ in SECTIONS if any(e["shelf"] == k for e in self.data["library"])), self.section)

    def content(self):
        d = self.d
        counts = {k: sum(1 for e in self.data["library"] if e["shelf"] == k) for k, _ in SECTIONS[:3]}
        counts["highlights"] = len(self.data["highlights"])
        out: list[ft.Control] = [d.segmented([(k, f"{label} {counts[k]}") for k, label in SECTIONS], self.section, self.set_section)]
        if self.section == "highlights":
            out += self._highlights()
        else:
            out += self._shelf([e for e in self.data["library"] if e["shelf"] == self.section])
        return out

    def set_section(self, s: str) -> None:
        self.section = s
        self.refresh()

    def _shelf(self, entries: list[dict]) -> list[ft.Control]:
        d = self.d
        if not entries:
            msg = {"reading": "읽고 있는 책이 없어요", "want": "읽고 싶은 책을 담아 두세요", "done": "아직 완독한 책이 없어요"}[self.section]
            return [w.empty(d, ft.Icons.AUTO_STORIES_OUTLINED, msg, "둘러보기에서 마음에 드는 책을 찾아보세요.", "둘러보기", lambda e: self.app.go_tab(1))]
        from saipr.views.book import BookScreen

        tiles = []
        for e in entries:
            book = {"id": e["book_id"], "title": e["title"], "author": e.get("author"), "cover_url": e.get("cover_url")}
            tiles.append(ft.Container(
                ft.Column([
                    w.cover(d, book, 100, hero=f"cover-{book['id']}"),
                    d.text(e["title"], 13, "semibold", max_lines=1, width=100),
                    ft.Container(d.progress(e.get("progress_pct", 0) / 100, 3), width=100),
                    d.text(f"{e.get('progress_pct', 0)}%" + ("" if e.get("has_fulltext") else " · 기록"), 11, muted=True),
                ], spacing=6, tight=True),
                on_click=lambda ev, b=book: self.app.push(BookScreen(self.app, f"/book/{b['id']}", book_id=b["id"], preview=b)),
            ))
        return [ft.Row(tiles, wrap=True, spacing=18, run_spacing=22)]

    def _highlights(self) -> list[ft.Control]:
        d = self.d
        hs = self.data["highlights"]
        if not hs:
            return [w.empty(d, ft.Icons.FORMAT_QUOTE_ROUNDED, "아직 밑줄이 없어요", "리더에서 문단을 길게 누르면 밑줄과 메모를 남길 수 있어요.")]
        by_book: dict[int, list[dict]] = {}
        for h in hs:
            by_book.setdefault((h.get("book") or {}).get("id") or h.get("book_id"), []).append(h)
        out: list[ft.Control] = []
        for _, items in by_book.items():
            book = items[0].get("book") or {"id": items[0].get("book_id"), "title": ""}
            out.append(ft.Row([w.cover(d, book, 30), d.text(book.get("title", ""), 15, "bold", expand=True), d.caption(f"{len(items)}개")], spacing=10))
            for h in items:
                out.append(self._highlight_card(h, book))
        return out

    def _highlight_card(self, h: dict, book: dict) -> ft.Control:
        d = self.d
        color = HIGHLIGHT_COLORS.get(h.get("color", "yellow"), "#FFD95A")
        card = d.card(ft.Column([
            ft.Row([ft.Container(width=4, height=40, bgcolor=color, border_radius=4),
                    ft.Text(f"“{h['quote']}”", size=15, font_family="Gowun Batang", color=d.p.fg, expand=True)],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            *([d.text(h["note"], 14, muted=True)] if h.get("note") else []),
            ft.Row([
                d.caption(f"{(h.get('chunk_index') or 0) + 1}쪽 · {fmt.ago(h.get('created_at'))} · {'팔로워 공개' if h.get('visibility') == 'friends' else '나만 보기'}", size=12),
                ft.Row([d.icon_button(ft.Icons.IOS_SHARE, lambda e: self.app.run(self.share(h, book)), "공유"),
                        d.icon_button(ft.Icons.DELETE_OUTLINE_ROUNDED, lambda e: self.app.run(self.delete(h)), "지우기")], spacing=0),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ], spacing=10), padding=16, radius=22)
        return ft.Dismissible(
            content=card, dismiss_direction=ft.DismissDirection.END_TO_START,
            background=ft.Container(ft.Icon(ft.Icons.DELETE_OUTLINE, color="#ffffff"), bgcolor=alpha("#ff3b30", 0.85),
                                    border_radius=22, alignment=ft.Alignment.CENTER_RIGHT, padding=ft.Padding.only(right=24)),
            on_dismiss=lambda e: self.app.run(self.delete(h, dismissed=True)),
        )

    async def share(self, h: dict, book: dict) -> None:
        text = f"“{h['quote']}”\n— {book.get('title', '')}" + (f"\n\n{h['note']}" if h.get("note") else "") + "\n\n#함께읽기"
        await self.app.share_text(text)

    async def delete(self, h: dict, dismissed: bool = False) -> None:
        ok = await self.app.guard(self.api.delete(f"/highlights/{h['id']}"))
        if ok:
            self.data["highlights"] = [x for x in self.data["highlights"] if x["id"] != h["id"]]
            self.app.toast("밑줄을 지웠어요")
        if ok or dismissed:  # 밀어서 없앤 카드는 실패해도 다시 그려서 트리에서 뺀다(실패면 되살아난다)
            self.refresh()
