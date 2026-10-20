"""둘러보기 — 검색 · 장르 · 인기 · 새로 들어온 책 · 외부 검색(트래커)."""

from __future__ import annotations

import flet as ft

from saipr.app import gather_safe
from saipr.core.api import ApiError, Offline
from saipr.ui import widgets as w
from saipr.views.base import Screen

GENRES = [("all", "전체"), ("소설", "소설"), ("시", "시"), ("수필", "수필")]
SOURCE = {"wikisource": "위키문헌", "gutendex": "Gutendex", "kakao": "카카오", "naver": "네이버", "google_books": "Google Books"}


class ExploreScreen(Screen):
    tab = 1
    large_title = "둘러보기"

    def __init__(self, app, route, **params):
        super().__init__(app, route, **params)
        self.genre = "all"
        self.query = ""
        self.results: dict | None = None
        self.searching = False
        self.search_field: ft.TextField | None = None

    async def load(self):
        genre = None if self.genre == "all" else self.genre
        popular, new = await gather_safe(
            self.api.get("/books", sort="popular", genre=genre, limit=12),
            self.api.get("/books", sort="new", genre=genre, limit=12),
        )
        self.data = {"popular": popular or [], "new": new or []}

    def stale(self):
        return self.data is None

    def content(self):
        d = self.d
        self.search_field = d.field("", self.query, hint="책 제목이나 작가 검색", icon=ft.Icons.SEARCH_ROUNDED,
                                    on_submit=lambda e: self.app.run(self.search(e.control.value)), key="search")
        out: list[ft.Control] = [self.search_field]
        if self.query:
            out += self._results()
            return out
        out.append(d.segmented(GENRES, self.genre, self.set_genre))
        popular, new = self.data["popular"], self.data["new"]
        if not popular and not new:
            out.append(w.empty(d, ft.Icons.MENU_BOOK_OUTLINED, "아직 책이 없어요", "검색해서 위키문헌의 공개 도서를 가져와 보세요."))
            return out
        if popular:
            out.append(d.section("지금 많이 읽는 책"))
            out.append(self._shelf(popular))
            top = popular[0]
            out.append(self._feature(top))
        if new:
            out.append(d.section("새로 들어온 책"))
            out.append(self._shelf(new))
        out.append(d.card(ft.Row([ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=18, color=self.d.p.muted),
                                  d.text("앱 안에서 읽는 책은 저작권이 끝난 공개 도서예요. 시판 도서는 검색해서 진행률만 기록할 수 있어요.", 12, muted=True, expand=True)],
                                 spacing=10), padding=14, radius=18))
        return out

    def set_genre(self, g: str) -> None:
        self.genre = g
        self.app.run(self.reload())

    def _shelf(self, books: list[dict]) -> ft.Control:
        d = self.d
        from saipr.views.book import BookScreen

        items = []
        for b in books:
            items.append(ft.Container(
                ft.Column([
                    w.cover(d, b, 104, hero=f"cover-{b['id']}"),
                    d.text(b["title"], 13, "semibold", max_lines=1, width=104),
                    d.text(b.get("author") or "", 11, muted=True, max_lines=1, width=104),
                ], spacing=6, tight=True),
                on_click=lambda e, b=b: self.app.push(BookScreen(self.app, f"/book/{b['id']}", book_id=b["id"], preview=b)),
            ))
        return ft.Row(items, spacing=14, scroll=ft.ScrollMode.HIDDEN)

    def _feature(self, b: dict) -> ft.Control:
        d = self.d
        from saipr.views.book import BookScreen

        readers = b.get("readers") or 0
        return d.card(ft.Row([
            w.cover(d, b, 76),
            ft.Column([
                d.caption("오늘의 추천"),
                d.text(b["title"], 20, "bold", max_lines=2),
                d.caption(f"{b.get('author') or '작자 미상'} · {readers}명이 읽는 중"),
                d.button("읽어 보기", lambda e: self.app.push(BookScreen(self.app, f"/book/{b['id']}", book_id=b["id"], preview=b)), kind="secondary"),
            ], spacing=6, expand=True),
        ], spacing=16), padding=18)

    async def search(self, q: str) -> None:
        self.query = (q or "").strip()
        if not self.query:
            self.results = None
            self.refresh()
            return
        self.searching, self.results = True, None
        self.refresh()
        try:
            local, remote = await gather_safe(
                self.api.get("/books", limit=30),
                self.api.get("/books/search", q=self.query, limit=10),
            )
        except (ApiError, Offline) as e:
            self.results = {"error": e.message}
        else:
            ql = self.query.lower()
            mine = [b for b in (local or []) if ql in b["title"].lower() or ql in (b.get("author") or "").lower()]
            known = {(b.get("source"), b.get("external_id")) for b in (local or [])}
            hits = [h for h in ((remote or {}).get("items") or []) if (h["source"], h["external_id"]) not in known]
            self.results = {"local": mine, "hits": hits, "errors": (remote or {}).get("errors") or {}}
        self.searching = False
        self.refresh()

    def _results(self) -> list[ft.Control]:
        d = self.d
        if self.searching or self.results is None:
            return [w.skeleton(d, 2), w.skeleton(d, 2)]
        if "error" in self.results:
            return [w.error_state(d, self.results["error"], lambda e: self.app.run(self.search(self.query)))]
        from saipr.views.book import BookScreen

        out: list[ft.Control] = [ft.Row([d.caption(f"“{self.query}” 검색 결과"),
                                         ft.TextButton(content=d.text("지우기", 13, "medium"), on_click=lambda e: self.app.run(self.search("")))],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN)]
        rows: list[ft.Control] = []
        for b in self.results["local"]:
            rows.append(w.list_row(d, w.cover(d, b, 44), b["title"], f"{b.get('author') or '작자 미상'} · 앱에 있어요",
                                   self._badge(b.get("has_fulltext")),
                                   on_click=lambda e, b=b: self.app.push(BookScreen(self.app, f"/book/{b['id']}", book_id=b["id"], preview=b))))
        for h in self.results["hits"]:
            meta = {"title": h["title"], "id": h["source"] + h["external_id"], "cover_url": h.get("cover_url")}
            rows.append(w.list_row(d, w.cover(d, meta, 44), h["title"],
                                   f"{', '.join(h.get('authors') or []) or '작자 미상'} · {SOURCE.get(h['source'], h['source'])}",
                                   self._badge(h.get("has_fulltext")),
                                   on_click=lambda e, h=h: self.app.run(self.add(h))))
        if not rows:
            out.append(w.empty(d, ft.Icons.SEARCH_OFF_ROUNDED, "찾는 책이 없어요", "다른 검색어로 찾아볼까요?"))
        else:
            out.append(d.card(ft.Column(rows, spacing=0), padding=ft.Padding.symmetric(horizontal=16, vertical=6)))
        if self.results["errors"]:
            out.append(d.caption("지금 응답하지 않는 곳: " + ", ".join(SOURCE.get(k, k) for k in self.results["errors"])))
        return out

    def _badge(self, fulltext: bool) -> ft.Control:
        return w.pill(self.d, "전문 읽기" if fulltext else "진행률 기록", icon=ft.Icons.MENU_BOOK if fulltext else ft.Icons.TIMELINE)

    async def add(self, h: dict) -> None:
        """검색 결과를 앱에 들인다: 공개 도서는 전문을 가져오고, 시판 도서는 트래커로 담는다."""
        from saipr.views.book import BookScreen

        self.app.toast("가져오는 중…" if h.get("has_fulltext") else "서재에 담는 중…")
        if h.get("has_fulltext"):
            book = await self.app.guard(self.api.post("/books/import", {"source": h["source"], "external_id": h["external_id"]}))
            book_id = book and book["id"]
        else:
            entry = await self.app.guard(self.api.post("/books/track", {
                "source": h["source"], "external_id": h["external_id"], "title": h["title"],
                "authors": h.get("authors") or [], "isbn13": h.get("isbn13"), "cover_url": h.get("cover_url"),
            }))
            book_id = entry and entry["book_id"]
        if book_id:
            self.app.haptic("medium")
            self.app.push(BookScreen(self.app, f"/book/{book_id}", book_id=book_id))
