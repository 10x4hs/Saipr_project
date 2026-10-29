"""공개 소개 페이지 (/intro) — 로그인 없이 누구나 볼 수 있다."""

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
DATA = BASE / "data"
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter(include_in_schema=False)


def _read(name: str, default):
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else default


def _counts() -> dict[str, int]:
    seen = {
        (b["title"].strip().lower(), (b.get("author") or "").strip().lower())
        for b in _read("catalog.json", [])
    }
    return {
        "classics": len(seen),
        "store": len(_read("store.json", [])),
        "videos": len(_read("videos.json", {})),
    }


COUNTS = _counts()


@router.get("/intro", response_class=HTMLResponse)
async def intro(request: Request):
    return templates.TemplateResponse(request, "intro.html", {"counts": COUNTS})
