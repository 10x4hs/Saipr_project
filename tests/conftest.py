import os
import tempfile
from collections.abc import AsyncIterator, Callable

# 앱을 import하기 전에 테스트 환경을 고정한다: 임시 SQLite 파일, 스케줄러 끔
_TMP = tempfile.mkdtemp(prefix="saipr-test-")
# 실제 앱 엔진을 쓰는 테스트(test_realtime)는 DATABASE_URL을 주면 그 DB(예: Postgres)로 돈다
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP}/app.db")
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["DB_DISABLE_POOL"] = "true"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["VAPID_KEY_FILE"] = f"{_TMP}/vapid.pem"

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402
from app.api.deps import get_http_client  # noqa: E402
from app.core import security  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.realtime.broker import broker  # noqa: E402

# 테스트에서는 scrypt 비용을 낮춘다 (저장 형식에 N이 들어가므로 검증은 그대로 동작)
security._N = 2**10

Handler = Callable[[httpx.Request], httpx.Response]


def mock_client(handler: Handler) -> httpx.AsyncClient:
    """외부 API를 흉내내는 httpx 클라이언트. 네트워크에 절대 나가지 않는다."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def no_network(req: httpx.Request) -> httpx.Response:
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def _clean_broker():
    from app.services import book_info

    broker.reset()
    book_info._failed_at.clear()
    yield
    broker.reset()
    book_info._failed_at.clear()


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
async def api(session_factory):
    """(handler) -> ASGI 테스트 클라이언트 팩토리. handler가 외부 API 응답을 결정한다."""
    clients: list[httpx.AsyncClient] = []

    async def _session() -> AsyncIterator:
        async with session_factory() as s:
            yield s

    def make(handler: Handler = no_network) -> httpx.AsyncClient:
        upstream = mock_client(handler)
        clients.append(upstream)
        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_http_client] = lambda: upstream
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield make
    app.dependency_overrides.clear()
    for c in clients:
        await c.aclose()


async def signup(c: httpx.AsyncClient, nickname: str = "서연", email: str | None = None) -> dict:
    """가입 + 로그인. 이후 요청에 CSRF 헤더가 자동으로 붙도록 클라이언트에 심어 둔다."""
    token = (await c.get("/api/v1/auth/csrf")).json()["csrf_token"]
    email = email or f"{nickname.encode().hex()}@test.kr"
    r = await c.post(
        "/api/v1/auth/signup",
        json={
            "nickname": nickname,
            "email": email,
            "password": "password123",
            "password_confirm": "password123",
        },
        headers={"X-CSRF-Token": token},
    )
    assert r.status_code == 201, r.text
    # 로그인하면 CSRF 토큰이 바뀐다
    c.headers["X-CSRF-Token"] = (await c.get("/api/v1/auth/csrf")).json()["csrf_token"]
    return r.json()


async def make_book(session_factory, paragraphs_per_chunk: list[list[str]], title: str = "테스트 책") -> int:
    """청크를 직접 넣은 전문 도서. 청크 하나 = 문단 목록."""
    async with session_factory() as s:
        book = models.Book(
            source="wikisource",
            external_id=title,
            title=title,
            language="ko",
            has_fulltext=True,
            total_chunks=len(paragraphs_per_chunk),
            chunks=[
                models.BookChunk(chunk_index=i, text="\n\n".join(ps), char_count=sum(map(len, ps)))
                for i, ps in enumerate(paragraphs_per_chunk)
            ],
        )
        s.add(book)
        await s.commit()
        return book.id


async def age_accounts(session_factory, hours: float = 48) -> None:
    """가입 시각을 과거로 돌린다. 체류시간 예산은 '가입 후 실제로 흐른 시간'이라, 몇 분 읽은 장면을 만들려면 필요하다."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    async with session_factory() as s:
        await s.execute(update(models.User).values(created_at=datetime.now(UTC) - timedelta(hours=hours)))
        await s.commit()


async def token_signup(c: httpx.AsyncClient, nickname: str = "앱사용자", email: str | None = None) -> dict:
    """네이티브 앱처럼 토큰으로 가입. 이후 요청에 Bearer 헤더가 붙는다(쿠키 · CSRF 없음)."""
    email = email or f"app-{nickname.encode().hex()}@test.kr"
    r = await c.post(
        "/api/v1/auth/token/signup",
        json={
            "nickname": nickname,
            "email": email,
            "password": "password123",
            "password_confirm": "password123",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    c.headers["Authorization"] = f"Bearer {body['token']}"
    return body["user"]


async def set_position(session_factory, user_id: int, book_id: int, verified_chunk: int) -> None:
    """체류시간 이벤트 없이 읽은 위치를 정한다(스포일러 가드 · 밑줄 위치 테스트용)."""
    from sqlalchemy import select

    async with session_factory() as s:
        e = await s.scalar(
            select(models.LibraryEntry).where(
                models.LibraryEntry.user_id == user_id, models.LibraryEntry.book_id == book_id
            )
        )
        if e is None:
            e = models.LibraryEntry(user_id=user_id, book_id=book_id, shelf=models.Shelf.READING)
            s.add(e)
        e.verified_chunk = verified_chunk
        e.progress_pct = 0
        await s.commit()
