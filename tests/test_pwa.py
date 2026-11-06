"""PWA 매니페스트·서비스 워커·안드로이드 TWA 연결 파일."""

from pathlib import Path

from app.core.config import get_settings
from tests.test_api import upstream

STATIC = Path(__file__).parents[1] / "app" / "static"


async def test_manifest_lists_installable_icons(api):
    async with api(upstream) as c:
        r = await c.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["display"] == "standalone" and m["start_url"].startswith("/")
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes and any(i["purpose"] == "maskable" for i in m["icons"])
    for icon in m["icons"]:
        assert (STATIC / icon["src"].removeprefix("/static/")).is_file()


async def test_service_worker_served_from_root(api):
    async with api(upstream) as c:
        r = await c.get("/sw.js")
        offline = await c.get("/static/offline.html")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert r.headers["service-worker-allowed"] == "/" and "no-cache" in r.headers["cache-control"]
    assert offline.status_code == 200


async def test_pages_link_manifest_and_register_worker(api):
    async with api(upstream) as c:
        html = (await c.get("/")).text
    assert 'rel="manifest" href="/manifest.webmanifest"' in html and "serviceWorker.register('/sw.js')" in html


async def test_landing_has_apk_download(api):
    async with api(upstream) as c:
        html = (await c.get("/")).text
        apk = await c.get("/static/haedok.apk")
    assert 'href="/static/haedok.apk"' in html and "download" in html
    assert apk.status_code == 200 and apk.content[:2] == b"PK"  # APK는 zip
    assert apk.headers["content-type"] == "application/vnd.android.package-archive"


async def test_assetlinks_uses_configured_fingerprints(api, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "android_cert_sha256", "aa:bb, cc:dd")
    async with api(upstream) as c:
        links = (await c.get("/.well-known/assetlinks.json")).json()
        monkeypatch.setattr(settings, "android_cert_sha256", "")
        empty = (await c.get("/.well-known/assetlinks.json")).json()
    target = links[0]["target"]
    assert links[0]["relation"] == ["delegate_permission/common.handle_all_urls"]
    assert target["package_name"] == settings.android_package
    assert target["sha256_cert_fingerprints"] == ["AA:BB", "CC:DD"]
    assert empty == []
