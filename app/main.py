from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import auth, web
from app.api import books, me
from app.core.config import get_settings

USER_AGENT = "saipr/0.1 (+https://github.com/hsK10x2/Saipr_project)"  # Wikimedia는 UA 명시 요구


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        app.state.http = client
        yield


app = FastAPI(title="함께읽기 API", version="0.1.0", lifespan=lifespan)
_settings = get_settings()
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
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
