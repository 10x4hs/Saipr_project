"""리더의 체류시간 측정 · 읽은 기록 큐 · 읽기 속도 학습. 화면과 무관한 순수 로직이라 단위 테스트가 쉽다.

서버 규칙(app/services/reading.py)과 짝을 이룬다: 앱은 '보고 있던 쪽'과 '머문 시간'만 보내고,
인정 여부는 서버가 다시 계산한다. 그래서 앱은 정직하게 재기만 하면 된다.

- 한 번에 한 쪽(청크)만 잰다. 쪽을 넘기거나, 앱이 백그라운드로 가거나, 10초가 지나면 구간을 닫는다.
- 300ms 미만으로 스친 쪽은 기록하지 않는다.
- 2분 넘게 손을 대지 않은 구간은 속도 학습에서 뺀다(딴짓).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

MIN_SEGMENT_MS = 300
FLUSH_EVERY_S = 10
IDLE_FOR_SPEED_MS = 120_000
DEFAULT_CPM = 500  # 한국어 성인 평균에 가까운 분당 글자 수
MAX_QUEUE = 1000


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


@dataclass
class DwellTracker:
    """지금 보고 있는 쪽에 머문 시간을 재고, 닫힌 구간을 이벤트로 만든다.

    시간은 단조 시계(monotonic)로 재고, 이벤트 시각(occurred_at)만 벽시계로 찍는다 —
    기기 시계를 바꿔도 머문 시간이 틀어지지 않는다.
    """

    clock: callable = time.monotonic
    wall: callable = lambda: datetime.now(UTC)  # noqa: E731
    current: int | None = None
    _start: float | None = None
    paused: bool = False
    events: list[dict] = field(default_factory=list)
    dwell_by_chunk: dict[int, int] = field(default_factory=dict)

    def _close(self) -> None:
        if self.current is None or self._start is None:
            return
        ms = int((self.clock() - self._start) * 1000)
        if ms >= MIN_SEGMENT_MS:
            self.events.append({"chunk_index": self.current, "dwell_ms": ms, "occurred_at": _iso(self.wall())})
            if ms < IDLE_FOR_SPEED_MS:
                self.dwell_by_chunk[self.current] = self.dwell_by_chunk.get(self.current, 0) + ms
        self._start = None if self.paused else self.clock()

    def show(self, chunk: int | None) -> None:
        """다른 쪽으로 넘겼다 (None이면 본문이 안 보이는 상태)."""
        if chunk == self.current:
            return
        self._close()
        self.current = chunk
        self._start = None if (chunk is None or self.paused) else self.clock()

    def pause(self) -> None:
        """앱이 백그라운드로 갔거나 화면이 꺼졌다 — 그동안은 세지 않는다."""
        if self.paused:
            return
        self._close()
        self.paused = True
        self._start = None

    def resume(self) -> None:
        if not self.paused:
            return
        self.paused = False
        self._start = None if self.current is None else self.clock()

    def tick(self) -> None:
        """주기적으로(10초) 지금 구간을 닫고 이어서 잰다 — 앱이 갑자기 꺼져도 잃는 시간이 짧다."""
        self._close()

    def drain(self) -> list[dict]:
        out, self.events = self.events, []
        return out


@dataclass
class EventQueue:
    """서버로 아직 못 보낸 읽은 기록. 저장소에 그대로 직렬화해 두었다가 연결되면 보낸다."""

    items: list[dict] = field(default_factory=list)

    def push(self, events: list[dict]) -> None:
        self.items.extend(events)
        if len(self.items) > MAX_QUEUE:
            self.items = self.items[-MAX_QUEUE:]

    def batch(self, size: int = 200) -> list[dict]:
        return self.items[:size]

    def ack(self, n: int) -> None:
        self.items = self.items[n:]

    def __len__(self) -> int:
        return len(self.items)


@dataclass
class SpeedModel:
    """내가 실제로 읽는 속도(분당 글자 수)를 배운다 — Kindle의 '남은 시간'과 같은 방식."""

    cpm: float = DEFAULT_CPM

    def learn(self, chars: int, dwell_ms: int) -> None:
        if chars <= 0 or dwell_ms <= 0:
            return
        sample = min(3000.0, max(150.0, chars / (dwell_ms / 60000)))
        self.cpm = self.cpm * 0.7 + sample * 0.3  # 지수 평균: 최근 쪽에 조금 더 무게

    def minutes(self, chars: int) -> int:
        return max(1, round(chars / self.cpm)) if chars > 0 else 0

    def eta_text(self, page_chars: int, remaining_chars: int) -> str:
        here = self.minutes(page_chars)
        rest = max(here, self.minutes(remaining_chars))
        rest_txt = f"{rest // 60}시간 {rest % 60}분" if rest >= 60 else f"{rest}분"
        return f"이 쪽 약 {here}분 · 끝까지 약 {rest_txt}"


MILESTONES = {25: "4분의 1 왔어요!", 50: "절반 왔어요! 🎉", 75: "거의 다 왔어요!", 100: "다 읽었어요! 📚"}


def crossed_milestone(before: int, after: int) -> int | None:
    """진행률이 이정표(25·50·75·100%)를 넘었으면 그 값 (여러 개면 가장 큰 것)."""
    hit = [m for m in MILESTONES if before < m <= after]
    return max(hit) if hit else None


def kst_greeting(now: datetime | None = None) -> str:
    h = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None) + timedelta(hours=9)
    hour = h.hour
    if hour < 5:
        return "늦은 밤에도"
    if hour < 11:
        return "좋은 아침,"
    if hour < 17:
        return "오늘도"
    if hour < 21:
        return "저녁에도"
    return "자기 전에"
