import re
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.deps import get_http_client
from app.db.base import Base
from app.db.session import get_session
from app.main import app

Handler = Callable[[httpx.Request], httpx.Response]


def mock_client(handler: Handler) -> httpx.AsyncClient:
    """외부 API를 흉내내는 httpx 클라이언트. 네트워크에 절대 나가지 않는다."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def api(session_factory):
    """(handler) -> ASGI 테스트 클라이언트 팩토리. handler가 외부 API 응답을 결정한다."""
    clients: list[httpx.AsyncClient] = []

    async def _session() -> AsyncIterator:
        async with session_factory() as s:
            yield s

    def make(handler: Handler) -> httpx.AsyncClient:
        upstream = mock_client(handler)
        clients.append(upstream)
        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_http_client] = lambda: upstream
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield make
    app.dependency_overrides.clear()


async def csrf_of(client: httpx.AsyncClient, path: str = "/signup") -> str:
    html = (await client.get(path)).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


async def signup(
    client: httpx.AsyncClient, email: str = "reader@example.com", nickname: str = "독자"
) -> None:
    """회원가입(= 로그인 상태)까지 마친다. 테스트용이라 비밀번호는 고정."""
    token = await csrf_of(client)
    r = await client.post(
        "/signup",
        data={
            "nickname": nickname,
            "email": email,
            "password": "password123",
            "password_confirm": "password123",
            "csrf": token,
        },
    )
    assert r.status_code == 303, r.text


@pytest.fixture
def clock(monkeypatch):
    """서버 시계를 앞으로 돌린다: clock(분)."""
    import datetime as dt

    from app.services import books as book_service

    state = {"now": dt.datetime.now(dt.UTC)}
    monkeypatch.setattr(book_service, "clock", lambda: state["now"])

    def advance(minutes: float = 10) -> None:
        state["now"] += dt.timedelta(minutes=minutes)

    return advance


async def read_chunk(client: httpx.AsyncClient, book_id, index: int, token: str, advance) -> dict:
    """쪽을 펼치고, 충분히 읽은 뒤(시계를 돌려) 다 읽었다고 보낸다."""
    headers = {"X-CSRF-Token": token}
    await client.put(f"/api/v1/books/{book_id}/progress", json={"chunk_index": index}, headers=headers)
    advance(10)
    r = await client.put(
        f"/api/v1/books/{book_id}/progress", json={"chunk_index": index, "verified": True}, headers=headers
    )
    return r.json()


@pytest.fixture(autouse=True)
def _reset_login_failures():
    """로그인 실패 기록은 프로세스 메모리라 테스트끼리 섞이지 않게 비운다."""
    from app import auth

    auth._failures.clear()
    yield
    auth._failures.clear()
