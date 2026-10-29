from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_url = get_settings().database_url
# Neon 같은 연결 풀러(pgbouncer, 트랜잭션 모드) 뒤에서는 asyncpg의 prepared statement 캐시가 깨진다
_args = {"statement_cache_size": 0} if "-pooler" in _url and _url.startswith("postgresql+asyncpg") else {}
engine = create_async_engine(_url, pool_pre_ping=True, connect_args=_args)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
