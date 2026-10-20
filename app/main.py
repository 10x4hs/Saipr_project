import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import models  # noqa: F401  (메타데이터 등록)
from app.api import auth, books, library, push, rooms, social, ws
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services import scheduler
from app.services.auth import AuthError
from app.services.battles import BattleError
from app.services.library import LibraryError
from app.services.points import ensure_challenges
from app.services.reactions import ReactionError
from app.services.reading import ReadingError
from app.services.rooms import RoomError
from app.services.teams import TeamError
from app.web import routes as web

# 앱 로그(스케줄러 정산 · 웹 푸시 결과)를 uvicorn 로그와 같은 곳에 남긴다
_app_log = logging.getLogger("app")
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)


def wants_html_page(request: Request) -> bool:
    return web.wants_html(request) and "text/html" in request.headers.get("accept", "")


USER_AGENT = "saipr/0.2 (+https://github.com/10x4hs/Saipr_project)"  # Wikimedia는 UA 명시 요구
STATIC_DIR = Path(__file__).parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        # 로컬 SQLite는 마이그레이션 없이 바로 테이블을 만든다. Postgres는 `alembic upgrade head`.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await ensure_challenges(session)

    task = (
        asyncio.create_task(scheduler.run_forever(settings.scheduler_interval_seconds))
        if settings.scheduler_enabled
        else None
    )
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        app.state.http = client
        yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="함께읽기 API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="saipr_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.session_cookie_secure,
    )
    for router in (
        auth.router,
        books.router,
        library.router,
        rooms.router,
        push.router,
        social.router,
        ws.router,
        web.router,
    ):
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    async def status_error(request: Request, exc: Exception) -> JSONResponse:
        if web.wants_html(request):
            return await web.error_page(request, exc)
        body = {"detail": str(exc)}
        if isinstance(exc, AuthError):
            body["errors"] = exc.errors
        return JSONResponse(body, status_code=getattr(exc, "status", 400))

    async def http_error(request: Request, exc: StarletteHTTPException):
        if wants_html_page(request):
            return await web.http_error_page(request, exc)
        return await http_exception_handler(request, exc)

    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(web.LoginRequired, lambda request, exc: web.login_redirect(request))

    for exc in (AuthError, RoomError, ReactionError, TeamError, BattleError, LibraryError, ReadingError):
        app.add_exception_handler(exc, status_error)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
