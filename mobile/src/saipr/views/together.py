"""함께 — 피드 · 친구 · 읽기방 · 리그. 그리고 배틀(밤 화면)과 팀 화면."""

from __future__ import annotations

import flet as ft

from saipr.app import gather_safe
from saipr.core import fmt
from saipr.ui import widgets as w
from saipr.ui.theme import alpha
from saipr.views.base import Screen

SECTIONS = [("feed", "피드"), ("friends", "친구"), ("rooms", "읽기방"), ("league", "리그")]
TIERS = ("브론즈", "실버", "골드", "다이아")


def activity_text(a: dict) -> str:
    who = (a.get("user") or {}).get("nickname", "누군가")
    title = (a.get("book") or {}).get("title", "")
    data = a.get("data") or {}
    kind = a.get("kind")
    if kind == "started":
        return f"{who}님이 「{title}」을 읽기 시작했어요"
    if kind == "milestone":
        return f"{who}님이 「{title}」을 {data.get('pct', '')}%까지 읽었어요"
    if kind == "finished":
        return f"{who}님이 「{title}」을 다 읽었어요 📚"
    if kind == "highlight":
        return f"{who}님이 「{title}」에 밑줄을 그었어요"
    if kind == "joined_room":
        return f"{who}님이 「{data.get('room_name', '')}」 방에 들어갔어요"
    if kind == "badge":
        return f"{who}님이 배지 ‘{data.get('title', '')}’를 받았어요 🏅"
    return f"{who}님의 소식"


class TogetherScreen(Screen):
    tab = 3
    large_title = "함께"

    def __init__(self, app, route, **params):
        super().__init__(app, route, **params)
        self.section = "feed"
        self.search_results: list[dict] | None = None

    async def load(self):
        feed, following, followers, rooms, teams, battles = await gather_safe(
            self.api.get("/feed", limit=30), self.api.get("/me/following"), self.api.get("/me/followers"),
            self.api.get("/rooms"), self.api.get("/teams"), self.api.get("/battles"),
        )
        league = None
        if teams:
            try:
                league = await self.api.get(f"/leagues/{teams[0]['id']}")
            except Exception:
                league = None
        self.data = {"feed": feed or [], "following": following or [], "followers": followers or [],
                     "rooms": rooms or [], "teams": teams or [], "battles": battles or [], "league": league}

    def content(self):
        d = self.d
        out: list[ft.Control] = [d.segmented(SECTIONS, self.section, self.set_section)]
        out += {"feed": self._feed, "friends": self._friends, "rooms": self._rooms, "league": self._league}[self.section]()
        return out

    def set_section(self, s: str) -> None:
        self.section = s
        self.refresh()

    # ── 피드 ───────────────────────────────────────
    def _feed(self) -> list[ft.Control]:
        d = self.d
        items = self.data["feed"]
        if not items:
            return [w.empty(d, ft.Icons.DYNAMIC_FEED_OUTLINED, "아직 소식이 없어요", "친구를 추가하면 친구가 읽는 책과 밑줄이 여기에 떠요.",
                            "친구 찾기", lambda e: self.set_section("friends"))]
        me = (self.app.user or {}).get("id")
        out = []
        for a in items:
            mine = (a.get("user") or {}).get("id") == me
            data = a.get("data") or {}
            body: list[ft.Control] = [d.text(activity_text(a), 15, "medium")]
            if a.get("kind") == "highlight" and data.get("quote"):
                body.append(ft.Container(ft.Text(f"“{data['quote']}”", size=14, font_family="Gowun Batang", color=d.p.fg),
                                         padding=ft.Padding.only(left=12), border=ft.Border.only(left=ft.BorderSide(3, "#FFD95A"))))
                if data.get("note"):
                    body.append(d.text(data["note"], 13, muted=True))
            footer = [d.caption(fmt.ago(a.get("created_at")), size=12)]
            if not mine:
                footer.append(ft.TextButton(content=d.text("👏 응원하기", 13, "medium"),
                                            on_click=lambda e, uid=a["user"]["id"]: self.app.run(self.cheer(uid))))
            body.append(ft.Row(footer, alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
            row = ft.Row([
                ft.Container(w.avatar(d, a.get("user"), 38), on_click=lambda e, u=a["user"]: self.open_user(u)),
                ft.Column(body, spacing=6, expand=True),
                *([ft.Container(w.cover(d, a["book"], 36), on_click=lambda e, b=a["book"]: self.open_book(b))] if a.get("book") else []),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)
            out.append(d.card(row, padding=16, radius=22))
        return out

    async def cheer(self, uid: int) -> None:
        r = await self.app.guard(self.api.post(f"/users/{uid}/cheer"), ok="응원을 보냈어요 👏")
        if r:
            self.app.haptic("medium")

    # ── 친구 ───────────────────────────────────────
    def _friends(self) -> list[ft.Control]:
        d = self.d
        code = (self.app.user or {}).get("friend_code") or "------"
        out: list[ft.Control] = [d.card(ft.Row([
            ft.Column([d.caption("내 친구 코드"), d.text(code, 26, "bold")], spacing=2, expand=True),
            d.icon_button(ft.Icons.COPY_ROUNDED, lambda e: self.app.run(self.app.copy(code, "친구 코드를 복사했어요")), "복사"),
            d.icon_button(ft.Icons.IOS_SHARE, lambda e: self.app.run(self.app.share_text(f"함께읽기에서 같이 읽어요! 친구 코드: {code}")), "공유"),
        ]), padding=18)]
        field = d.field("", hint="닉네임이나 친구 코드로 찾기", icon=ft.Icons.PERSON_SEARCH_ROUNDED,
                        on_submit=lambda e: self.app.run(self.search(e.control.value)), key="friend-search")
        out.append(field)
        if self.search_results is not None:
            if self.search_results:
                out.append(d.card(ft.Column([self._user_row(u, follow=True) for u in self.search_results], spacing=0),
                                  padding=ft.Padding.symmetric(horizontal=16, vertical=6)))
            else:
                out.append(d.caption("찾는 사람이 없어요"))
        following, followers = self.data["following"], self.data["followers"]
        out.append(d.section(f"팔로잉 {len(following)}"))
        if following:
            out.append(d.card(ft.Column([self._user_row(u) for u in following], spacing=0), padding=ft.Padding.symmetric(horizontal=16, vertical=6)))
        else:
            out.append(d.caption("체험 계정이라면 ‘준호’, ‘서연’을 검색해 보세요."))
        ids = {u["id"] for u in following}
        back = [u for u in followers if u["id"] not in ids]
        if back:
            out.append(d.section("나를 팔로우해요"))
            out.append(d.card(ft.Column([self._user_row({**u, "is_following": False}, follow=True) for u in back], spacing=0),
                              padding=ft.Padding.symmetric(horizontal=16, vertical=6)))
        return out

    def _user_row(self, u: dict, follow: bool = False) -> ft.Control:
        d = self.d
        trailing = None
        if follow and u.get("id") != (self.app.user or {}).get("id"):
            trailing = d.button("팔로잉" if u.get("is_following") else "팔로우", lambda e, u=u: self.app.run(self.toggle_follow(u)),
                                kind="secondary" if u.get("is_following") else "primary")
        return w.list_row(d, w.avatar(d, u, 40), u["nickname"], u.get("bio") or None, trailing, on_click=lambda e, u=u: self.open_user(u))

    async def search(self, q: str) -> None:
        q = (q or "").strip()
        if not q:
            self.search_results = None
        else:
            self.search_results = await self.app.guard(self.api.get("/users/search", q=q)) or []
        self.refresh()

    async def toggle_follow(self, u: dict) -> None:
        if u.get("is_following"):
            ok = await self.app.guard(self.api.delete(f"/users/{u['id']}/follow"))
        else:
            ok = await self.app.guard(self.api.post(f"/users/{u['id']}/follow"), ok=f"{u['nickname']}님을 팔로우했어요")
        if ok:
            self.app.haptic("medium")
            u["is_following"] = not u.get("is_following")
            await self.reload()

    def open_user(self, u: dict) -> None:
        from saipr.views.profile import UserScreen

        self.app.push(UserScreen(self.app, f"/user/{u['id']}", user_id=u["id"], preview=u))

    def open_book(self, b: dict) -> None:
        from saipr.views.book import BookScreen

        self.app.push(BookScreen(self.app, f"/book/{b['id']}", book_id=b["id"], preview=b))

    # ── 읽기방 ─────────────────────────────────────
    def _rooms(self) -> list[ft.Control]:
        d = self.d
        from saipr.views.home import HomeScreen

        out: list[ft.Control] = []
        code = d.field("", hint="초대 코드 8자리", icon=ft.Icons.KEY_ROUNDED, on_submit=lambda e: self.app.run(self.join(e.control.value)), key="room-code")
        out.append(d.card(ft.Column([d.text("초대 코드로 들어가기", 15, "semibold"), code], spacing=10), padding=18))
        rooms = self.data["rooms"]
        if not rooms:
            out.append(w.empty(d, ft.Icons.GROUPS_OUTLINED, "아직 들어간 방이 없어요", "책 화면에서 ‘방 만들기’를 눌러 친구를 초대해 보세요."))
        for r in rooms:
            out.append(HomeScreen._room_card(self, r))
        return out

    async def join(self, code: str) -> None:
        code = (code or "").strip().rstrip("/").rsplit("/", 1)[-1]
        if not code:
            return
        room = await self.app.guard(self.api.post(f"/invites/{code}/join"))
        if room:
            self.app.haptic("medium")
            from saipr.views.room import RoomScreen

            self.app.push(RoomScreen(self.app, f"/room/{room['id']}", room_id=room["id"]))

    # ── 리그 ───────────────────────────────────────
    def _league(self) -> list[ft.Control]:
        d = self.d
        out: list[ft.Control] = []
        league, teams = self.data["league"], self.data["teams"]
        my_ids = {t["id"] for t in teams}
        if league:
            out.append(ft.Column([d.caption(f"{TIERS[min(3, len(league) // 3)]} 리그 · 월요일 00:00 리셋"), d.text("이번 주 리그", 26, "bold")], spacing=2))
            rows = []
            for row in league:
                me = row["team_id"] in my_ids
                if row["rank"] == 4:
                    rows.append(ft.Container(height=1, gradient=ft.LinearGradient(colors=[ft.Colors.TRANSPARENT, alpha(d.p.fg, 0.6), ft.Colors.TRANSPARENT])))
                rows.append(ft.Container(ft.Row([
                    ft.Container(d.text(str(row["rank"]), 13, "bold", color="#ffffff" if me else None), width=28, height=28, border_radius=28,
                                 alignment=ft.Alignment.CENTER, bgcolor="#1d1d1f" if me else alpha(d.p.fg, 0.12)),
                    d.text(row["name"] + (" · 우리 팀" if me else ""), 15, "bold" if me else "regular", color="#1d1d1f" if me else None, expand=True),
                    d.text(f"평균 {fmt.num(float(row['average']))}청크", 13, color="#5d5e66" if me else None, muted=not me),
                ], spacing=12), padding=ft.Padding.symmetric(horizontal=14, vertical=12), border_radius=20,
                    bgcolor=alpha("#ffffff", 0.92) if me else None,
                    on_click=lambda e, t=row["team_id"]: self.open_team(t)))
            out.append(d.card(ft.Column(rows, spacing=2), padding=8))
        for b in [b for b in self.data["battles"] if b.get("status") != "finished"]:
            from saipr.views.home import HomeScreen

            out.append(HomeScreen._battle_card(self, b))
        out.append(d.section("내 팀"))
        for t in teams:
            out.append(d.card(ft.Row([d.text(t["name"], 16, "semibold", expand=True), d.caption(f"{len(t.get('members', []))}명"),
                                      ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=d.p.muted)]),
                              padding=16, radius=20, on_click=lambda e, t=t: self.open_team(t["id"])))
        name = d.field("", hint="새 팀 이름", icon=ft.Icons.GROUP_ADD_OUTLINED, max_length=40,
                       on_submit=lambda e: self.app.run(self.create_team(e.control.value)), key="team-name")
        code = d.field("", hint="팀 초대 코드", icon=ft.Icons.KEY_ROUNDED, on_submit=lambda e: self.app.run(self.join_team(e.control.value)), key="team-code")
        out.append(d.card(ft.Column([d.text("팀 만들기 · 참여", 15, "semibold"), name, code,
                                     d.caption("2명 이상 모이면 다른 팀에 페이지 레이스를 걸 수 있어요.")], spacing=10), padding=18))
        return out

    def open_team(self, team_id: int) -> None:
        self.app.push(TeamScreen(self.app, f"/team/{team_id}", team_id=team_id))

    async def create_team(self, name: str) -> None:
        if not (name or "").strip():
            return
        t = await self.app.guard(self.api.post("/teams", {"name": name.strip()}), ok="팀을 만들었어요")
        if t:
            self.open_team(t["id"])

    async def join_team(self, code: str) -> None:
        if not (code or "").strip():
            return
        t = await self.app.guard(self.api.post(f"/teams/join/{code.strip()}"), ok="팀에 들어갔어요")
        if t:
            self.open_team(t["id"])


class TeamScreen(Screen):
    title = "팀"

    def __init__(self, app, route, team_id: int):
        super().__init__(app, route)
        self.team_id = team_id

    async def load(self):
        teams, league, battles, library = await gather_safe(
            self.api.get("/teams"), self.api.get(f"/leagues/{self.team_id}"), self.api.get("/battles"), self.api.get("/library"))
        team = next((t for t in (teams or []) if t["id"] == self.team_id), None)
        self.data = {"team": team, "league": league or [], "battles": [b for b in (battles or []) if self.team_id in (b["team_a"]["team_id"], b["team_b"]["team_id"])],
                     "books": [e for e in (library or []) if e.get("has_fulltext")]}
        self.title = (team or {}).get("name") or "팀"

    def content(self):
        d = self.d
        team = self.data["team"]
        out: list[ft.Control] = []
        if team:
            out.append(d.card(ft.Column([
                d.caption(f"팀 · {len(team['members'])}/6명"),
                d.text(team["name"], 28, "bold"),
                ft.Row([w.avatar(d, {"nickname": n, "id": i}, 34) for i, n in enumerate(team["members"])], spacing=6, wrap=True),
                ft.Row([d.text(f"초대 코드 {team.get('invite_code') or ''}", 14, "semibold", expand=True),
                        d.icon_button(ft.Icons.COPY_ROUNDED, lambda e: self.app.run(self.app.copy(team.get("invite_code") or "", "팀 코드를 복사했어요")))]),
            ], spacing=10), padding=20))
        for b in self.data["battles"]:
            from saipr.views.home import HomeScreen

            out.append(HomeScreen._battle_card(self, b))
        rivals = [r for r in self.data["league"] if r["team_id"] != self.team_id]
        if team and rivals and self.data["books"]:
            out.append(d.section("다른 팀에 도전하기"))
            book = ft.Dropdown(options=[ft.DropdownOption(key=str(e["book_id"]), text=e["title"]) for e in self.data["books"]],
                               value=str(self.data["books"][0]["book_id"]), label="책")
            rival = ft.Dropdown(options=[ft.DropdownOption(key=str(r["team_id"]), text=r["name"]) for r in rivals], value=str(rivals[0]["team_id"]), label="상대 팀")
            kind = ft.Dropdown(options=[ft.DropdownOption(key="page_race", text="페이지 레이스"), ft.DropdownOption(key="highlight_battle", text="한줄평 배틀")],
                               value="page_race", label="종류")

            async def challenge(e):
                from datetime import UTC, datetime, timedelta

                now = datetime.now(UTC)
                b = await self.app.guard(self.api.post("/battles", {
                    "type": kind.value, "book_id": int(book.value), "team_a_id": self.team_id, "team_b_id": int(rival.value),
                    "starts_at": now.isoformat(), "ends_at": (now + timedelta(days=7)).isoformat()}), ok="도전을 보냈어요! 7일 동안 겨뤄요")
                if b:
                    self.app.push(BattleScreen(self.app, f"/battle/{b['id']}", battle_id=b["id"]))

            out.append(d.card(ft.Column([kind, book, rival, d.button("도전 보내기", challenge, icon=ft.Icons.FLAG_ROUNDED),
                                         d.caption("두 팀 모두 2명 이상이어야 해요. 배틀이 끝날 때까지 팀원은 바뀌지 않아요.")], spacing=12,
                                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH), padding=18))
        return out


class BattleScreen(Screen):
    title = "배틀"
    night = True

    def __init__(self, app, route, battle_id: int):
        super().__init__(app, route)
        self.battle_id = battle_id

    async def load(self):
        b, hs = await gather_safe(self.api.get(f"/battles/{self.battle_id}"), self.api.get(f"/battles/{self.battle_id}/highlights"))
        self.data = {"battle": b, "highlights": hs or []}

    def content(self):
        d = self.d
        b = self.data["battle"]
        me = (self.app.user or {}).get("id")
        a, bb = b["team_a"], b["team_b"]
        mine, theirs = (a, bb) if any(m.get("user_id") == me for m in a.get("members", [])) else (bb, a)
        total = (mine["average"] + theirs["average"]) or 1
        status = b.get("status")
        headline = fmt.time_left(b.get("ends_at")) if status == "active" else ("곧 시작해요" if status == "scheduled" else "배틀이 끝났어요")
        # 밤 배경은 글래스에만 있다 — 다른 디자인에서는 그 디자인의 글자색
        white = "#ffffff" if d.is_glass else d.p.fg
        out: list[ft.Control] = [ft.Column([d.text(f"{'페이지 레이스' if b['type'] == 'page_race' else '한줄평 배틀'} · {b.get('book_title', '')}", 13, color=alpha(white, 0.75)),
                                            d.text(headline, 32, "bold", color=white)], spacing=4)]
        score = lambda v, op: ft.Text(fmt.num(float(v)), size=60, font_family="Pretendard Bold", color=alpha(white, op))  # noqa: E731
        out.append(d.card(ft.Row([
            ft.Column([d.text(f"우리 팀 · {mine['name']}", 13, "medium", color="#8fd0ff"), score(mine["average"], 1), d.text("팀 평균 청크", 11, color=alpha(white, 0.7))], spacing=0),
            d.text("vs", 15, color=alpha(white, 0.5)),
            ft.Column([d.text(theirs["name"], 13, color=alpha(white, 0.75)), score(theirs["average"], 0.6), d.text("팀 평균 청크", 11, color=alpha(white, 0.7))],
                      spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), padding=22, radius=30))
        out.append(ft.ProgressBar(value=mine["average"] / total, color="#2997ff", bgcolor=alpha(white, 0.12), bar_height=10, border_radius=5))
        out.append(d.text(f"우리 팀이 함께 {mine['total']}청크를 읽었어요", 14, color=white, align=ft.TextAlign.CENTER))
        rows = [ft.Row([d.text("나" if m.get("user_id") == me else m["nickname"], 14, "bold" if m.get("user_id") == me else "regular", color=white),
                        d.text(f"{m['chunks']} 청크", 14, "medium", color=white)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                for m in sorted(mine.get("members", []), key=lambda m: -m["chunks"])]
        out.append(d.card(ft.Column([d.text("팀 기여", 16, "bold", color=white), *rows], spacing=12), padding=20, radius=26))
        out.append(d.card(ft.Row([ft.Icon(ft.Icons.SCHEDULE, size=16, color=alpha(white, 0.8)),
                                  d.text("빠르게 넘긴 청크는 점수에 반영되지 않아요. 천천히 읽어도 괜찮아요.", 12, color=white, expand=True)], spacing=10), padding=14, radius=18))
        if b["type"] == "highlight_battle":
            for h in self.data["highlights"]:
                out.append(d.card(ft.Column([
                    ft.Text(f"“{h['quote']}”", size=15, font_family="Gowun Batang", color=white),
                    *([d.text(h["comment"], 13, color=alpha(white, 0.8))] if h.get("comment") else []),
                    ft.Row([d.text(f"{h['nickname']} · {h['votes']}표", 12, color=alpha(white, 0.7)),
                            *([d.button("투표", lambda e, h=h: self.app.run(self.vote(h)), kind="secondary")] if (status == "active" and not h.get("voted_by_me") and h.get("user_id") != me) else [])],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ], spacing=8), padding=16, radius=22))
        if status != "finished":
            from saipr.views.reader import ReaderScreen

            out.append(d.button("이어 읽고 점수 올리기", lambda e: self.app.push(ReaderScreen(self.app, f"/read/{b['book_id']}", book_id=b["book_id"])),
                                icon=ft.Icons.AUTO_STORIES))
        return out

    async def vote(self, h: dict) -> None:
        if await self.app.guard(self.api.post(f"/battles/{self.battle_id}/highlights/{h['id']}/vote"), ok="투표했어요"):
            self.app.haptic("medium")
            await self.reload()
