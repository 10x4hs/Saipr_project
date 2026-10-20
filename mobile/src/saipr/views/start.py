"""시작 화면 — 로그인 · 가입 · 서버 주소 · 체험 계정."""

from __future__ import annotations

import flet as ft

from saipr.core import fmt
from saipr.core.api import ApiError, Offline
from saipr.ui.theme import alpha
from saipr.views.base import Screen

DEMO = [("서연", "seoyeon@demo.kr"), ("준호", "junho@demo.kr")]
DEMO_PASSWORD = "demo1234"


def orb(size: float = 104) -> ft.Control:
    """시안의 유리 구슬 마스코트 (얼굴 · 윗면 하이라이트 · 무지개 반사)."""
    face = ft.Container(
        width=size * 0.34, height=size * 0.26, border_radius=7, border=ft.Border.all(3, alpha("#ffffff", 0.92)),
        content=ft.Row([ft.Container(width=3, height=7, bgcolor="#ffffff", border_radius=2)] * 2,
                       spacing=7, alignment=ft.MainAxisAlignment.CENTER),
    )
    return ft.Stack([
        ft.Container(width=size, height=size, border_radius=size,
                     gradient=ft.RadialGradient(colors=[alpha("#ffffff", 0.06), alpha("#ffffff", 0.14), alpha("#ffffff", 0.6)], stops=[0, 0.7, 1]),
                     border=ft.Border.all(1, alpha("#ffffff", 0.6)),
                     shadow=[ft.BoxShadow(blur_radius=60, spread_radius=6, color=alpha("#ffffff", 0.4)),
                             ft.BoxShadow(blur_radius=30, offset=ft.Offset(0, 12), color=alpha("#000000", 0.18))]),
        ft.Container(width=size * 0.5, height=size * 0.24, border_radius=size, left=size * 0.22, top=size * 0.04,
                     gradient=ft.RadialGradient(colors=[alpha("#ffffff", 0.85), alpha("#ffffff", 0.0)])),
        ft.Container(width=size * 0.34, height=size * 0.1, border_radius=size, left=size * 0.12, top=size * 0.62,
                     gradient=ft.LinearGradient(colors=["#ff8fd0b3", "#8ff0ffb3", "#fff38f99"])),
        ft.Container(face, left=size * 0.33, top=size * 0.33),
        ft.Container(width=size * 0.4, height=3, bgcolor=alpha("#ffffff", 0.8), border_radius=2, left=size * 0.3, top=size * 0.66),
    ], width=size, height=size)


class StartScreen(Screen):
    def __init__(self, app, route, server: str | None = None):
        super().__init__(app, route)
        self.mode = "login"
        self.busy = False
        self.errors: dict[str, str] = {}
        self.server_ok: bool | None = None
        self.loading = False
        self.data = {}
        self.f_nick = self.f_email = self.f_pw = self.f_pw2 = None

    def header(self):
        return None

    async def load(self):
        self.server_ok = await self.api.health()

    async def on_show(self):
        await self.reload()

    def content(self):
        d = self.d
        greet = ft.Row([
            ft.Column([d.text("같은 책을, 각자의 속도로", 14, muted=True), d.title("오늘도\n함께 읽어요")], spacing=4, expand=True),
            orb(),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

        self.f_email = d.field("이메일", self.f_email.value if self.f_email else "", keyboard=ft.KeyboardType.EMAIL,
                               icon=ft.Icons.MAIL_OUTLINE_ROUNDED, key="email")
        self.f_pw = d.field("비밀번호", "", password=True, icon=ft.Icons.LOCK_OUTLINE_ROUNDED, key="password",
                            on_submit=lambda e: self.app.run(self.submit()))
        fields: list[ft.Control] = []
        if self.mode == "signup":
            self.f_nick = d.field("닉네임", self.f_nick.value if self.f_nick else "", icon=ft.Icons.FACE_ROUNDED, max_length=40, key="nickname")
            self.f_pw2 = d.field("비밀번호 확인", "", password=True, icon=ft.Icons.LOCK_OUTLINE_ROUNDED, key="password2",
                                 on_submit=lambda e: self.app.run(self.submit()))
            fields += [self.f_nick, self._err("nickname")]
        fields += [self.f_email, self._err("email"), self.f_pw, self._err("password")]
        if self.mode == "signup":
            fields += [self.f_pw2, self._err("password_confirm")]
        if self.errors.get("form"):
            fields.append(d.text(self.errors["form"], 13, color=d.p.danger))

        form = d.card(ft.Column([
            d.segmented([("login", "로그인"), ("signup", "가입")], self.mode, self.switch_mode),
            *fields,
            ft.Container(height=4),
            d.button("시작하기" if self.mode == "signup" else "로그인", lambda e: self.app.run(self.submit()),
                     disabled=self.busy, key="submit"),
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), padding=20)

        demo = ft.Column([
            d.caption("체험 계정으로 바로 둘러보기"),
            ft.Row([d.button(f"{fmt.ro(n)} 시작", lambda e, m=m: self.app.run(self.demo(m)), kind="secondary", expand=True)
                    for n, m in DEMO], spacing=10),
        ], spacing=8)

        dot = "#34c759" if self.server_ok else ("#ff3b30" if self.server_ok is False else alpha(d.p.fg, 0.4))
        status = "연결됨" if self.server_ok else ("연결 안 됨" if self.server_ok is False else "확인 중")
        server = ft.Container(
            ft.Row([ft.Container(width=8, height=8, bgcolor=dot, border_radius=8),
                    d.text(f"서버 {self.api.base_url} · {status}", 12, muted=True, max_lines=1, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=16, color=d.p.muted)], spacing=8),
            padding=ft.Padding.symmetric(horizontal=6, vertical=10), on_click=lambda e: self.server_sheet(), key="server",
        )
        return [ft.Container(height=20), greet, form, demo, server]

    def _err(self, key: str) -> ft.Control:
        msg = self.errors.get(key)
        return self.d.text(msg, 12, color=self.d.p.danger) if msg else ft.Container(height=0)

    def switch_mode(self, mode: str) -> None:
        self.mode, self.errors = mode, {}
        self.refresh()

    async def submit(self) -> None:
        if self.busy:
            return
        self.busy, self.errors = True, {}
        email, pw = (self.f_email.value or "").strip(), self.f_pw.value or ""
        try:
            if self.mode == "signup":
                user = await self.api.signup((self.f_nick.value or "").strip(), email, pw, self.f_pw2.value or "")
            else:
                user = await self.api.login(email, pw)
        except ApiError as e:
            self.errors = e.errors or {"form": e.message}
            self.app.haptic("heavy")
        except Offline as e:
            self.errors = {"form": e.message}
            self.server_ok = False
        else:
            self.app.haptic("medium")
            await self.app.login_done(user)
            return
        finally:
            self.busy = False
        self.refresh()

    async def demo(self, email: str) -> None:
        self.mode = "login"
        self.refresh()
        self.f_email.value, self.f_pw.value = email, DEMO_PASSWORD
        await self.submit()

    def server_sheet(self) -> None:
        d = self.d
        field = d.field("서버 주소", self.api.base_url, hint="예: 192.168.0.10:8000 또는 https://…", keyboard=ft.KeyboardType.URL, key="server-field")
        note = ft.Text("", size=13, font_family="Pretendard", color="#6c6c70")

        async def save(e=None):
            self.api.set_base(field.value or "")
            note.value = "연결을 확인하는 중…"
            note.update()
            ok = await self.api.health()
            self.server_ok = ok
            if ok:
                await self.app.store.set("server", self.api.base_url)
                self.app.close_dialog()
                self.app.toast("서버에 연결했어요")
                self.refresh()
            else:
                note.value = "이 주소에서 서버를 찾지 못했어요. 같은 와이파이인지, 서버가 켜져 있는지 확인해 주세요."
                note.update()

        field.on_submit = lambda e: self.app.run(save())
        self.app.sheet(ft.Column([
            ft.Text("서버 주소", size=20, font_family="Pretendard Bold", color="#1d1d1f" if not d.dark else "#ffffff"),
            ft.Text("노트북에서 서버를 켰다면 같은 와이파이에서 그 노트북의 IP:8000을 입력하세요.", size=13,
                    font_family="Pretendard", color="#6c6c70"),
            field, note,
            ft.Button(content=ft.Text("연결", font_family="Pretendard SemiBold"), on_click=lambda e: self.app.run(save())),
        ], spacing=12, tight=True))
