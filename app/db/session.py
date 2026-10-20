from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.realtime.broker import broker

_settings = get_settings()
_url = _settings.database_url
# SQLite 파일은 연결을 여는 비용이 거의 없어 풀을 두지 않는다(이벤트 루프가 바뀌어도 안전).
if _url.startswith("sqlite"):
    _engine_opts: dict[str, Any] = {"connect_args": {"timeout": 15}, "poolclass": NullPool}
elif _settings.db_disable_pool:
    _engine_opts = {"poolclass": NullPool}
else:
    _engine_opts = {"pool_pre_ping": True}
engine = create_async_engine(_url, **_engine_opts)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


# ── 트랜잭션 아웃박스 ────────────────────────────────────────────
# 서비스 코드는 이벤트를 바로 보내지 않고 세션에 쌓아 둔다. 커밋이 성공했을 때만 브로커로 내보내서
# "DB에는 없는데 화면에는 뜬" 이벤트가 생기지 않게 한다. 롤백되면 버린다.

_OUTBOX = "outbox"


def defer_publish(session: AsyncSession, channel: str, type: str, data: dict[str, Any]) -> None:
    sync = session.sync_session
    # 트랜잭션이 아직 없으면 시작해 둔다. 그래야 이후 rollback이 after_rollback 훅을 반드시 부른다.
    if not sync.in_transaction():
        sync.begin()
    sync.info.setdefault(_OUTBOX, []).append((channel, type, data))


@event.listens_for(Session, "after_commit")
def _flush_outbox(session: Session) -> None:
    for channel, type, data in session.info.pop(_OUTBOX, []):
        broker.publish(channel, type, data)


@event.listens_for(Session, "after_rollback")
def _drop_outbox(session: Session) -> None:
    session.info.pop(_OUTBOX, None)
