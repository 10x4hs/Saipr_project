"""앱 상태와 화면 이동.

- 상태: 서버 주소 · 토큰 · 디자인 · 내 정보 · 안 읽은 알림 수 · 기기 서비스(진동 · 화면 꺼짐 방지 · 공유 · 저장소)
- 이동: 탭(go_tab)은 스택을 그 탭 하나로 바꾸고, 상세 화면(push)은 위에 쌓고, 뒤로가기(pop·밀어서)는 하나 뺀다.
  화면 객체는 스택에 있는 동안 살아 있어서, 뒤로 돌아오면 스크롤·입력이 그대로다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable

import flet as ft

from saipr.core.api import Api, ApiError, Offline
from saipr.core.realtime import Realtime
from saipr.core.store import Store
from saipr.core.sync import ReadingSync, SessionExpired
from saipr.ui.theme import Design, alpha

log = logging.getLogger(__name__)
DEFAULT_SERVER = os.environ.get("SAIPR_SERVER", "http://127.0.0.1:8000")
TABS = ("home", "explore", "library", "together", "me")


class App:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.store = Store(ft.SharedPreferences())
        self.haptics = ft.HapticFeedback()
        self.wakelock = ft.Wakelock()
        self.share = ft.Share()
        self.clipboard = ft.Clipboard()
        self.launcher = ft.UrlLauncher()
        self.api = Api(DEFAULT_SERVER)
        self.design = Design()
        self.user: dict | None = None
        self.unread = 0
        self.stack: list = []
        self.realtime = Realtime(lambda path: self.api.ws_url(path), self._realtime_rejected)
        self.sync = ReadingSync(self.api, self.store, lambda: (self.user or {}).get("id"))
        self.me_channel_handler = None
        self._tasks: set[asyncio.Task] = set()

    # ── 시작 ───────────────────────────────────────
    async def start(self) -> None:
        page = self.page
        page.title = "함께읽기"
        page.on_view_pop = self._on_view_pop
        page.on_app_lifecycle_state_change = self._on_lifecycle
        prefs = await self.store.get("settings", {}) or {}
        self.design = Design(prefs.get("design", "glass"), bool(prefs.get("dark", False)))
        self.design.apply(page)
        server = await self.store.get("server")
        self.api.set_base(server or DEFAULT_SERVER)
        self.api.token = await self.store.get("token")
        self.user = await self.store.get("user")
        if self.api.token:
            try:
                self.user = await self.api.get("/auth/me")
                await self.store.set("user", self.user)
            except ApiError as e:
                if e.status == 401:
                    self.api.token = None
            except Offline:
                pass  # 오프라인이어도 저장해 둔 내 정보로 시작한다 (받아 둔 책은 읽을 수 있다)
        if not self.api.token and os.environ.get("SAIPR_DEMO_LOGIN"):
            await self._dev_login()
        if self.api.token and self.user:
            self.after_login()
            self.go_tab(0)
            self._dev_open()
        else:
            from saipr.views.start import StartScreen

            self.set_stack([StartScreen(self, "/start", server=server)])

    # ── 개발용 훅: 환경변수로 자동 로그인 · 디자인 · 화면 열기 (스크린샷 자동화) ─────────
    async def _dev_login(self) -> None:
        email, _, password = os.environ["SAIPR_DEMO_LOGIN"].partition(":")
        try:
            self.user = await self.api.login(email, password or "demo1234")
        except (ApiError, Offline) as e:
            log.warning("dev login failed: %s", e)
        design = os.environ.get("SAIPR_DESIGN")  # 예: glass:dark
        if design:
            name, _, mode = design.partition(":")
            self.design = Design(name, mode == "dark")
            self.design.apply(self.page)

    def _dev_open(self) -> None:
        spec = os.environ.get("SAIPR_OPEN")
        if not spec:
            return
        kind, _, arg = spec.partition(":")
        self.open(kind, arg)

    def open(self, kind: str, arg: str = "") -> bool:
        """이름으로 화면 열기 — 개발용 SAIPR_OPEN과 알림 링크가 같이 쓴다."""
        if kind == "tab":
            self.go_tab(int(arg))
            return True
        from saipr.views import book, me, profile, reader, room, together

        screens = {
            "book": lambda: book.BookScreen(self, f"/book/{arg}", book_id=int(arg)),
            "read": lambda: reader.ReaderScreen(self, f"/read/{arg}", book_id=int(arg)),
            "room": lambda: room.RoomScreen(self, f"/room/{arg}", room_id=int(arg)),
            "user": lambda: profile.UserScreen(self, f"/user/{arg}", user_id=int(arg)),
            "battle": lambda: together.BattleScreen(self, f"/battle/{arg}", battle_id=int(arg)),
            "team": lambda: together.TeamScreen(self, f"/team/{arg}", team_id=int(arg)),
            "settings": lambda: me.SettingsScreen(self, "/settings"),
            "notifications": lambda: me.NotificationsScreen(self, "/notifications"),
        }
        if kind not in screens:
            return False
        self.push(screens[kind]())
        return True

    def open_link(self, link: str | None) -> bool:
        """서버 알림의 링크(/rooms/3, /books/1/read?chunk=4 …)를 앱 화면으로 바꿔 연다."""
        target = link_target(link)
        return self.open(*target) if target else False

    def after_login(self) -> None:
        self.realtime.close_all()
        ch = self.realtime.channel("/ws/me")

        async def on_me(ev: dict) -> None:
            if ev.get("type") == "notification.created":
                self.unread += 1
                self.toast("🔔 " + ev["data"]["body"])
                self.haptic("light")

        self.me_channel_handler = on_me
        ch.subscribe(on_me)
        self.run(self._refresh_unread())
        self.run(self._send_pending())

    def _realtime_rejected(self, path: str) -> None:
        if path == "/ws/me" and self.user:  # 내 채널이 거절됐다 = 토큰이 더 이상 유효하지 않다
            self.run(self.session_expired())

    async def _send_pending(self) -> None:
        try:
            await self.sync.send_pending()
        except SessionExpired:
            await self.session_expired()

    async def _refresh_unread(self) -> None:
        try:
            items = await self.api.get("/notifications")
            self.unread = sum(1 for n in items if not n.get("read"))
        except (ApiError, Offline):
            pass

    async def login_done(self, data_user: dict) -> None:
        self.user = data_user
        await self.store.set("token", self.api.token)
        await self.store.set("user", data_user)
        await self.store.set("server", self.api.base_url)
        self.after_login()
        self.go_tab(0)

    async def logout(self) -> None:
        # 실시간 채널 안(이벤트 처리 중)에서 불려도 끝까지 가도록: 상태를 먼저 지우고, 채널은 맨 마지막에 닫는다.
        # 아직 못 보낸 읽은 기록은 계정별로 기기에 남겨 두었다가 그 계정으로 다시 로그인하면 보낸다.
        for k in ("token", "user"):
            await self.store.remove(k)
        try:
            await self.api.logout()
        except Exception:
            self.api.token = None
        self.user, self.unread = None, 0
        from saipr.views.start import StartScreen

        self.set_stack([StartScreen(self, "/start", server=self.api.base_url)])
        self.realtime.close_all()

    async def session_expired(self) -> None:
        self.toast("로그인이 만료됐어요. 다시 로그인해 주세요.")
        await self.logout()

    # ── 디자인 ─────────────────────────────────────
    async def set_design(self, name: str | None = None, dark: bool | None = None) -> None:
        self.design = Design(name or self.design.name, self.design.dark if dark is None else dark)
        self.design.apply(self.page)
        await self.store.set("settings", {"design": self.design.name, "dark": self.design.dark})
        # 화면을 새 재질로 다시 그린다 (데이터는 그대로)
        for s in self.stack:
            s.view = None
        self._render()

    # ── 이동 ───────────────────────────────────────
    def _make_tab(self, i: int):
        from saipr.views import explore, home, library, me, together

        cls = (home.HomeScreen, explore.ExploreScreen, library.LibraryScreen, together.TogetherScreen, me.MeScreen)[i]
        return cls(self, "/" + TABS[i])

    def go_tab(self, i: int) -> None:
        current = self.stack[0] if self.stack else None
        if current is not None and current.tab == i and len(self.stack) == 1:
            self.run(current.reload())  # 같은 탭을 다시 누르면 새로고침
            return
        self.haptic("selection")
        self.set_stack([self._make_tab(i)])

    def set_stack(self, screens: list) -> None:
        for s in self.stack:
            if s not in screens:
                s.on_hide()
        self.stack = screens
        self._render()
        self.run(self.stack[-1].on_show())

    def push(self, screen) -> None:
        self.stack.append(screen)
        self._render()
        self.run(screen.on_show())

    def pop(self) -> None:
        if len(self.stack) <= 1:
            return
        top = self.stack.pop()
        top.on_hide()
        self._render()
        self.run(self.stack[-1].on_show())

    def _render(self) -> None:
        self.page.views.clear()
        for s in self.stack:
            self.page.views.append(s.view or s.build())
        self.page.update()

    async def _on_view_pop(self, e: ft.ViewPopEvent) -> None:
        self.pop()

    async def _on_lifecycle(self, e: ft.AppLifecycleStateChangeEvent) -> None:
        top = self.stack[-1] if self.stack else None
        handler = getattr(top, "on_lifecycle", None)
        if handler:
            await handler(e.state)

    # ── 공통 도우미 ───────────────────────────────────
    def run(self, coro: Awaitable) -> None:
        """백그라운드 작업 시작. 참조를 들고 있어야 끝나기 전에 사라지지 않는다."""
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("background task failed", exc_info=task.exception())

    async def guard(self, coro: Awaitable, ok: str | None = None) -> object | None:
        """버튼 동작용: 성공하면 ok 문구, 실패하면 서버가 보낸 이유를 토스트로. 실패하면 None."""
        try:
            result = await coro
        except Offline as e:
            self.toast(e.message)
            return None
        except ApiError as e:
            if e.status == 401:
                await self.session_expired()
                return None
            self.toast(e.message)
            return None
        if ok:
            self.toast(ok)
        # 본문 없는 성공(204)도 참으로 — 실패(None)와 구분된다
        return True if result is None else result

    def toast(self, message: str, action: str | None = None, on_action: Callable | None = None) -> None:
        d = self.design
        bar = ft.SnackBar(
            content=ft.Text(message, font_family="Pretendard Medium", color="#ffffff", size=14),
            bgcolor=alpha("#1d1d1f", 0.9), behavior=ft.SnackBarBehavior.FLOATING,
            shape=ft.RoundedRectangleBorder(radius=9999 if d.is_glass else 14),
            margin=ft.Margin.only(left=24, right=24, bottom=96 if d.is_glass else 16), duration=3200,
            action=action, on_action=on_action,
        )
        self.page.show_dialog(bar)

    def haptic(self, kind: str = "light") -> None:
        if self.page.web:
            return  # 웹은 진동이 없고, 브라우저가 경고를 남긴다

        async def go():
            try:
                await {"light": self.haptics.light_impact, "medium": self.haptics.medium_impact,
                       "heavy": self.haptics.heavy_impact, "selection": self.haptics.selection_click}[kind]()
            except Exception:
                pass  # 진동이 없는 기기(데스크톱·웹)

        self.run(go())

    def sheet(self, content: ft.Control, scrollable: bool = True) -> ft.BottomSheet:
        d = self.design
        bg = "#f5f5f7" if (d.is_glass and not d.dark) else (alpha("#1c1c1e", 0.98) if d.dark else d.p.surface)
        bs = ft.BottomSheet(
            content=ft.Container(content, padding=ft.Padding.only(left=20, right=20, top=4, bottom=28)),
            show_drag_handle=True, draggable=True, scrollable=scrollable, use_safe_area=True, bgcolor=bg,
            shape=ft.RoundedRectangleBorder(radius=28), barrier_color=alpha("#000000", 0.25),
        )
        self.page.show_dialog(bs)
        return bs

    def close_dialog(self) -> None:
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    async def copy(self, text: str, message: str = "복사했어요") -> None:
        try:
            await self.clipboard.set(text)
            self.toast(message)
        except Exception:
            self.toast(text)

    async def share_text(self, text: str) -> None:
        try:
            await self.share.share_text(text)
        except Exception:
            await self.copy(text, "공유할 수 없어서 복사했어요")


def link_target(link: str | None) -> tuple[str, str] | None:
    m = re.match(r"^/(rooms|books|battles|teams|users)/(\d+)(/read)?", link or "")
    if m:
        kind = {"rooms": "room", "books": "read" if m[3] else "book", "battles": "battle", "teams": "team", "users": "user"}[m[1]]
        return kind, m[2]
    if (link or "").startswith("/me"):
        return "tab", "4"
    return None


async def gather_safe(*coros: Awaitable) -> list:
    """여러 요청을 한꺼번에. 하나가 실패해도 나머지는 받는다(실패한 자리는 None). 모두 실패하면 첫 오류를 올린다."""
    results = await asyncio.gather(*coros, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    if errors and len(errors) == len(results):
        raise errors[0]
    return [None if isinstance(r, Exception) else r for r in results]
