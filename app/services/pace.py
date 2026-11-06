"""체류시간(dwell time) 검증 — 퀴즈를 대체하는 치팅 방지 규칙 (PRD BTL-01).

기준: 쪽(청크)마다 똑같이 15초. 글자 크기·글자 수·화면 크기와 상관없다.
서버가 잰 시간으로만 판정하고, 리더(reader.js)는 서버가 내려준 min_dwell_ms를 그대로 센다.
시연용 배율(DWELL_SCALE)은 app.services.books.required_dwell_ms 가 곱한다.
"""

PAGE_DWELL_MS = 15_000
# 예전 이름 — 이제 모든 쪽이 같은 시간이라 하한도 같다
MIN_DWELL_MS = PAGE_DWELL_MS
# 탭을 켜두고 방치해 체류시간을 부풀리는 것 방지 (PRD EXC-04)
DWELL_CAP_MULTIPLIER = 10


def counted_chars(text: str) -> int:
    """공백을 뺀 글자 수 — 판정에는 쓰지 않고 통계용으로만 남긴다."""
    return sum(not c.isspace() for c in text)


def min_dwell_ms(text: str = "", language: str | None = None) -> int:
    """한 쪽을 '다 읽었다'고 인정하는 최소 체류시간. 모든 쪽이 15초."""
    del text, language  # 글자 수·언어와 무관하다
    return PAGE_DWELL_MS


def credited_dwell_ms(dwell_ms: int, min_ms: int) -> int:
    return max(0, min(dwell_ms, min_ms * DWELL_CAP_MULTIPLIER))


def is_verified(total_dwell_ms: int, min_ms: int) -> bool:
    """같은 청크 재방문 시 누적 체류시간으로 판정한다."""
    return total_dwell_ms >= min_ms
