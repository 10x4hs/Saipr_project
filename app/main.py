from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import web
from app.api import books
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
app.include_router(books.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
