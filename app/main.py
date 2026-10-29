import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import auth, web
from app.api import books, me, social
from app.core.config import Settings, get_settings

USER_AGENT = "saipr/0.1 (+https://github.com/hsK10x2/Saipr_project)"  # Wikimedia는 UA 명시 요구


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        # 임시 배포(서버리스 /tmp SQLite)·로컬 시연용: 테이블이 없으면 만든다. Postgres는 Alembic이 맡는다
        from app import models  # noqa: F401
        from app.db.base import Base
        from app.db.session import engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        app.state.http = client
        yield


app = FastAPI(title="함께읽기 API", version="0.1.0", lifespan=lifespan)
_settings = get_settings()
if os.environ.get("VERCEL") and _settings.secret_key == Settings.model_fields["secret_key"].default:
    # 기본 키는 공개 저장소에 있어 누구나 세션 쿠키를 위조할 수 있다
    raise RuntimeError("SECRET_KEY 환경 변수를 설정해야 배포할 수 있어요")
app.add_middleware(
    SessionMiddleware,
    secret_key=_settings.secret_key,
    session_cookie="session",
    max_age=_settings.session_idle_minutes * 60,
    same_site="lax",
    https_only=_settings.cookie_secure,
)


@app.exception_handler(auth.LoginRequired)
async def to_login(request: Request, exc: auth.LoginRequired) -> RedirectResponse:
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


app.include_router(books.router)
app.include_router(me.router)
app.include_router(social.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
