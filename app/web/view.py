"""화면 표시용 도우미 — 템플릿 필터, 시안의 사진 배경, 남은 시간 문구.

규칙은 services/에 두고 여기서는 보여 주기만 한다.
"""

import zlib
from datetime import datetime

from markupsafe import Markup

from app.core.clock import KST, aware, utcnow

# 시안 Glass v2의 아바타·표지 색
AVATAR_COLORS = ("#3b82f6", "#22a06b", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6", "#ec4899", "#64748b")
COVER_COLORS = ("#8e6c4a", "#b5523b", "#3a5a8c", "#2f6b4f", "#6b4f8e", "#8c3a5a", "#4a7a8c", "#7a6a3a")
WEEKDAYS = "월화수목금토일"


def av_color(user_id: int) -> str:
    return AVATAR_COLORS[user_id % len(AVATAR_COLORS)]


def initial(nickname: str) -> str:
    return (nickname or "?")[:1]


def cover_color(key: str | int) -> str:
    return COVER_COLORS[zlib.crc32(str(key).encode()) % len(COVER_COLORS)]


def kst_today() -> str:
    d = utcnow().astimezone(KST)
    return f"{d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일"


def num(x: float) -> str:
    """점수 표시: 128.0 → '128', 2.45 → '2.5'."""
    return f"{round(x, 1):g}"


def clock() -> str:
    """PC 폰 프레임 상단의 시계 (strftime의 %-H는 Windows에서 안 돼서 직접 만든다)."""
    d = utcnow().astimezone(KST)
    return f"{d.hour}:{d.minute:02d}"


def time_left(end: datetime | None, now: datetime | None = None) -> str:
    """'2일 14시간 남음' · '3시간 남음' · '끝났어요'."""
    if end is None:
        return ""
    secs = int((aware(end) - (now or utcnow())).total_seconds())
    if secs <= 0:
        return "끝났어요"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    if days:
        return f"{days}일 {hours}시간 남음" if hours else f"{days}일 남음"
    if hours:
        return f"{hours}시간 남음"
    return f"{max(1, rem // 60)}분 남음"


def dday(end: datetime | None) -> str:
    if end is None:
        return ""
    days = (aware(end).astimezone(KST).date() - utcnow().astimezone(KST).date()).days
    return "D-day" if days == 0 else (f"D-{days}" if days > 0 else "종료")


def date_label(end: datetime | None) -> str:
    if end is None:
        return ""
    d = aware(end).astimezone(KST)
    return f"{d.month}월 {d.day}일({WEEKDAYS[d.weekday()]})"


def _blob(x: float, y: float, w: float, h: float, bg: str, blur: float) -> str:
    # 시안은 390×844 기준 px 좌표 — 화면 크기가 달라도 같은 자리에 오도록 %로 바꾼다
    return (
        f'<i style="left:{x / 390 * 100:.2f}%;top:{y / 844 * 100:.2f}%;width:{w}px;height:{h}px;'
        f'background:{bg};filter:blur({blur}px)"></i>'
    )


def _backdrop(night: bool) -> Markup:
    """시안의 photoBg(): 하늘 빛 + 블러 처리한 초원 · 꽃 보케 · (밤이면) 별."""
    parts = [
        _blob(
            70,
            -120,
            300,
            300,
            f"radial-gradient(closest-side, rgb(255 255 255 / {0.35 if night else 0.95}), transparent)",
            30,
        )
    ]
    for x, y, w, h, day, nite in (
        (-120, 560, 420, 340, "#3c5530", "#16241a"),
        (160, 600, 420, 320, "#55703f", "#1d2b1e"),
        (-40, 690, 480, 260, "#2e4426", "#101a12"),
    ):
        parts.append(_blob(x, y, w, h, nite if night else day, 45))
    for x, y, w, h in (
        (30, 640, 90, 50),
        (120, 610, 70, 40),
        (250, 630, 110, 55),
        (310, 700, 80, 45),
        (60, 740, 120, 60),
        (200, 720, 90, 50),
    ):
        parts.append(_blob(x, y, w, h, "rgb(111 127 143 / .25)" if night else "rgb(241 239 230 / .8)", 16))
    for x, y, w in ((150, 650, 26), (280, 610, 20), (90, 700, 18)):
        parts.append(_blob(x, y, w, w, f"rgb(232 195 90 / {0.2 if night else 0.7})", 5))
    if night:
        for x, y in ((40, 90), (320, 60), (260, 140), (110, 200), (350, 230), (190, 40)):
            parts.append(_blob(x, y, 3, 3, "#fff", 0.5))
    return Markup(f'<div class="bg" aria-hidden="true">{"".join(parts)}</div>')


BACKDROP_DAY = _backdrop(False)
BACKDROP_NIGHT = _backdrop(True)


def register(env) -> None:
    env.filters.update(
        av=av_color,
        num=num,
        initial=initial,
        cover=cover_color,
        left=time_left,
        dday=dday,
        datelabel=date_label,
    )
    env.globals.update(BACKDROP_DAY=BACKDROP_DAY, BACKDROP_NIGHT=BACKDROP_NIGHT, kst_today=kst_today)
