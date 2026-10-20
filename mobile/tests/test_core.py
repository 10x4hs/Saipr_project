"""앱 핵심 로직: 체류시간 측정 · 큐 · 속도 학습 · API 클라이언트."""

import json

import httpx
import pytest

from saipr.core.api import Api, ApiError, Offline, normalize_base
from saipr.core.reading import DwellTracker, EventQueue, SpeedModel, crossed_milestone
from saipr.core.store import Store


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def tracker():
    c = FakeClock()
    return DwellTracker(clock=c), c


def test_dwell_counts_only_the_page_on_screen():
    t, c = tracker()
    t.show(0)
    c.t += 30
    t.show(1)  # 0쪽 30초 → 기록
    c.t += 0.1
    t.show(2)  # 1쪽 0.1초 → 스친 것, 기록 안 함
    c.t += 5
    t.tick()  # 10초 주기: 2쪽 5초 닫고 이어서 잰다
    events = t.drain()
    assert [(e["chunk_index"], e["dwell_ms"]) for e in events] == [(0, 30000), (2, 5000)]
    assert t.drain() == []


def test_background_time_is_not_counted():
    t, c = tracker()
    t.show(0)
    c.t += 10
    t.pause()  # 앱이 백그라운드로
    c.t += 600  # 10분 동안 다른 앱
    t.resume()
    c.t += 4
    t.tick()
    assert [e["dwell_ms"] for e in t.drain()] == [10000, 4000]


def test_idle_segments_are_excluded_from_speed_learning():
    t, c = tracker()
    t.show(3)
    c.t += 200  # 3분 20초 동안 손대지 않음
    t.tick()
    assert t.dwell_by_chunk.get(3) is None
    assert t.drain()[0]["dwell_ms"] == 200000  # 서버로는 보낸다 (판정은 서버가)


def test_queue_caps_and_acks():
    q = EventQueue()
    q.push([{"i": i} for i in range(1200)])
    assert len(q) == 1000 and q.items[0] == {"i": 200}
    assert len(q.batch(200)) == 200
    q.ack(200)
    assert len(q) == 800


def test_speed_model_learns_and_estimates():
    s = SpeedModel()
    for _ in range(10):
        s.learn(chars=1000, dwell_ms=60000)  # 분당 1000자
    assert 950 < s.cpm < 1000
    assert s.minutes(2000) == 2
    assert s.eta_text(1000, 1000 * 70).startswith("이 쪽 약 1분 · 끝까지 약 1시간")
    s.learn(chars=10, dwell_ms=1)  # 터무니없는 값은 상한에 걸린다
    assert s.cpm <= 3000


def test_milestones():
    assert crossed_milestone(20, 30) == 25
    assert crossed_milestone(10, 80) == 75
    assert crossed_milestone(50, 50) is None
    assert crossed_milestone(99, 100) == 100


def test_normalize_base():
    assert normalize_base(" 192.168.0.5:8000/ ") == "http://192.168.0.5:8000"
    assert normalize_base("https://saipr.app") == "https://saipr.app"


def mock_api(handler):
    return Api("http://test", transport=httpx.MockTransport(handler))


async def test_api_sends_bearer_and_parses_errors():
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers.get("authorization")
        if req.url.path == "/api/v1/auth/token":
            return httpx.Response(200, json={"token": "tok123", "user": {"id": 1, "nickname": "서연"}})
        if req.url.path == "/api/v1/rooms/9":
            return httpx.Response(404, json={"detail": "방을 찾을 수 없어요."})
        if req.url.path == "/api/v1/bad":
            return httpx.Response(422, json={"detail": [{"loc": ["body"], "msg": "x"}]})
        return httpx.Response(204)

    api = mock_api(handler)
    user = await api.login("a@b.kr", "pw")
    assert user["nickname"] == "서연" and api.token == "tok123"
    with pytest.raises(ApiError) as e:
        await api.get("/rooms/9")
    assert e.value.status == 404 and e.value.message == "방을 찾을 수 없어요."
    assert seen["auth"] == "Bearer tok123"
    with pytest.raises(ApiError) as e:
        await api.post("/bad")
    assert e.value.message == "입력한 값을 다시 확인해 주세요."
    assert await api.delete("/x") is None
    assert api.ws_url("/ws/rooms/1") == "ws://test/ws/rooms/1?token=tok123"


async def test_api_offline_is_distinct():
    def handler(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(Offline):
        await mock_api(handler).get("/books")


class FakePrefs:
    def __init__(self):
        self.d = {}

    async def get(self, k):
        return self.d.get(k)

    async def set(self, k, v):
        self.d[k] = v
        return True

    async def remove(self, k):
        self.d.pop(k, None)


async def test_store_roundtrip_and_offline_books():
    prefs = FakePrefs()
    s = Store(prefs)
    await s.set("token", "abc")
    await s.save_chunk(3, 0, {"paragraphs": ["봄봄"]})
    fresh = Store(prefs)  # 앱을 다시 켠 것처럼
    assert await fresh.get("token") == "abc"
    assert (await fresh.chunk(3, 0))["paragraphs"] == ["봄봄"]
    assert await fresh.get("offline_books") == [3]
    assert json.loads(prefs.d["saipr.token"]) == "abc"
