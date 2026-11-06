"""PWA·안드로이드 앱(TWA) 연결 파일.

- /manifest.webmanifest, /sw.js: 서비스 워커는 사이트 전체(/)를 맡아야 해서 루트 경로로 내보낸다
- /.well-known/assetlinks.json: 안드로이드 TWA 앱이 이 사이트의 것임을 증명 (주소창 없이 열림)
"""

import mimetypes
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import get_settings

router = APIRouter(include_in_schema=False)
# 서버리스 이미지에 따라 .apk 형식을 모를 수 있어 직접 등록한다 (안드로이드가 설치 파일로 알아보게)
mimetypes.add_type("application/vnd.android.package-archive", ".apk")
STATIC = Path(__file__).parent / "static"

MANIFEST = {
    "id": "/",
    "name": "偕讀 해독 — 같은 책을 함께 읽다",
    "short_name": "해독",
    "description": "같은 책을 각자의 속도로 함께 읽는 소셜 독서 앱",
    "lang": "ko",
    "start_url": "/?source=pwa",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#0a0a0a",
    "theme_color": "#0a0a0a",
    "categories": ["books", "education", "social"],
    "icons": [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {
            "src": "/static/icons/icon-maskable-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ],
}


@router.get("/manifest.webmanifest")
async def manifest() -> JSONResponse:
    return JSONResponse(
        MANIFEST, media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"}
    )


@router.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(
        STATIC / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


def asset_links() -> list[dict]:
    settings = get_settings()
    prints = [p.strip().upper() for p in settings.android_cert_sha256.split(",") if p.strip()]
    if not prints:
        return []
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": settings.android_package,
                "sha256_cert_fingerprints": prints,
            },
        }
    ]


@router.get("/.well-known/assetlinks.json")
async def assetlinks() -> JSONResponse:
    return JSONResponse(asset_links(), headers={"Cache-Control": "public, max-age=3600"})
