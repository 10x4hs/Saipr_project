"""체류시간(dwell time) 검증 — 퀴즈를 대체하는 치팅 방지 규칙 (PRD BTL-01).

기준: 글자 크기 18px로 한 화면(페이지)에 들어가는 만큼을 읽는 데 30초.
청크의 필요 시간 = 30초 × (청크 글자 수 / 기준 페이지 글자 수). 최소 8초.
글자 수는 서버가 본문에서 직접 센다 — 클라이언트의 글꼴·화면 크기가 판정에 끼어들지 않는다.
"""

import math

PAGE_DWELL_MS = 30_000
MIN_DWELL_MS = 8_000
# 18px, 모바일 한 화면(약 390×590px, 줄간격 1.95)에 들어가는 공백 제외 글자 수
BASELINE_PAGE_CHARS = {"ko": 300}
DEFAULT_BASELINE_PAGE_CHARS = 600  # 라틴 문자는 한 글자 폭이 대략 절반
# 탭을 켜두고 방치해 체류시간을 부풀리는 것 방지 (PRD EXC-04)
DWELL_CAP_MULTIPLIER = 10


def _is_korean(text: str, language: str | None) -> bool:
    if language:
        return language == "ko"
    letters = sum(c.isalnum() for c in text)
    hangul = sum("가" <= c <= "힣" for c in text)
    return letters > 0 and hangul / letters > 0.5


def counted_chars(text: str) -> int:
    """공백을 뺀 글자 수 — 판정의 유일한 입력."""
    return sum(not c.isspace() for c in text)


def baseline_chars(text: str, language: str | None = None) -> int:
    return BASELINE_PAGE_CHARS["ko"] if _is_korean(text, language) else DEFAULT_BASELINE_PAGE_CHARS


def min_dwell_ms(text: str, language: str | None = None) -> int:
    pages = counted_chars(text) / baseline_chars(text, language)
    return max(MIN_DWELL_MS, math.ceil(PAGE_DWELL_MS * pages))


def credited_dwell_ms(dwell_ms: int, min_ms: int) -> int:
    return max(0, min(dwell_ms, min_ms * DWELL_CAP_MULTIPLIER))


def is_verified(total_dwell_ms: int, min_ms: int) -> bool:
    """같은 청크 재방문 시 누적 체류시간으로 판정한다."""
    return total_dwell_ms >= min_ms
