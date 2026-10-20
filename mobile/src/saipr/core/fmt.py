"""화면에 보여 줄 문구 — 상대 시간, 날짜, 분, 숫자."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

KST = timedelta(hours=9)
WEEKDAYS = "월화수목금토일"


def parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def ago(ts: str | None, now: datetime | None = None) -> str:
    dt = parse(ts)
    if dt is None:
        return ""
    secs = int(((now or datetime.now(UTC)) - dt).total_seconds())
    if secs < 60:
        return "방금"
    if secs < 3600:
        return f"{secs // 60}분 전"
    if secs < 86400:
        return f"{secs // 3600}시간 전"
    if secs < 86400 * 7:
        return f"{secs // 86400}일 전"
    local = dt + KST
    return f"{local.month}월 {local.day}일"


def today_label(now: datetime | None = None) -> str:
    d = (now or datetime.now(UTC)).astimezone(UTC) + KST
    return f"{d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일"


def clock(ts: str | None) -> str:
    dt = parse(ts)
    if dt is None:
        return ""
    local = dt + KST
    return f"{local.hour}:{local.minute:02d}"


def minutes(n: float | int | None) -> str:
    n = int(round(n or 0))
    if n >= 60:
        return f"{n // 60}시간 {n % 60}분" if n % 60 else f"{n // 60}시간"
    return f"{n}분"


def time_left(ts: str | None, now: datetime | None = None) -> str:
    dt = parse(ts)
    if dt is None:
        return ""
    secs = int((dt - (now or datetime.now(UTC))).total_seconds())
    if secs <= 0:
        return "끝났어요"
    days, rem = divmod(secs, 86400)
    hours = rem // 3600
    if days:
        return f"{days}일 {hours}시간 남음" if hours else f"{days}일 남음"
    return f"{hours}시간 남음" if hours else f"{max(1, rem // 60)}분 남음"


def num(x: float | int | None) -> str:
    x = x or 0
    return f"{round(x, 1):g}" if isinstance(x, float) else f"{x:,}"


WJ = "\u2060"  # 단어 잇기 문자(보이지 않음) — 이 자리에서는 줄을 바꾸지 않는다


def keep_all(text: str) -> str:
    """한국어 줄바꿈을 단어 단위로 (CSS word-break: keep-all).

    Flutter는 한글을 글자마다 끊어 '만\\n다'처럼 단어가 쪼개진다. 단어 안의 글자 사이에 단어 잇기 문자를 넣어
    공백에서만 줄이 바뀌게 한다. 공백·줄바꿈은 그대로 둔다.
    """
    out = []
    for token in re.split(r"(\s+)", text):
        out.append(token if (not token or token.isspace()) else WJ.join(token))
    return "".join(out)


def ro(word: str) -> str:
    """조사 '(으)로' — 받침이 있으면 '으로', 없거나 ㄹ 받침이면 '로' (서연으로 · 준호로 · 서울로)."""
    last = word[-1:] or " "
    code = ord(last) - 0xAC00
    if not 0 <= code < 11172:
        return word + "(으)로"
    jong = code % 28
    return word + ("로" if jong in (0, 8) else "으로")
