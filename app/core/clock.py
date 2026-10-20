"""시간 규칙을 한곳에 모은다. 저장은 UTC, 하루·주 경계는 KST 기준 (PRD TEAM-01: 월요일 00:00 KST 리셋)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime) -> datetime:
    """항상 UTC로 맞춘다. SQLite는 tz를 버리고 돌려주고(→ UTC로 되붙임),
    +09:00 같은 오프셋이 붙은 값은 그대로 저장하면 SQLite가 시각만 남겨 9시간 밀리므로 UTC로 바꾼다.
    DB에 넣는 시각은 모두 이 함수를 거친다."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def kst_date(dt: datetime) -> date:
    return aware(dt).astimezone(KST).date()


def kst_day_start(dt: datetime) -> datetime:
    """dt가 속한 KST 날짜의 00:00을 UTC로."""
    return datetime.combine(kst_date(dt), time(), KST).astimezone(UTC)


def kst_week_start(dt: datetime) -> datetime:
    """dt가 속한 주의 월요일 00:00 KST를 UTC로."""
    d = kst_date(dt)
    return datetime.combine(d - timedelta(days=d.weekday()), time(), KST).astimezone(UTC)


def week_key(dt: datetime) -> str:
    y, w, _ = kst_date(dt).isocalendar()
    return f"{y}-W{w:02d}"
