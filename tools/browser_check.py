"""실제 브라우저 엔진으로 화면을 점검한다 — 안드로이드(Chromium · Pixel 7)와 아이폰(WebKit · iPhone 15).

서버를 켜 두고(시드 데이터 포함) 실행한다. Playwright는 프로젝트 의존성이 아니라서 따로 설치한다.

    pip install playwright && playwright install chromium webkit
    python tools/browser_check.py                  # http://localhost:8000
    python tools/browser_check.py --base http://localhost:8765 --shots out/

확인하는 것: 11개 화면이 폰 폭을 넘지 않는지, 탭 바가 바닥에서 떠 있는지, 자바스크립트 오류가 없는지,
움직임 줄이기 설정에서 내용이 바로 보이는지, 그리고 그 기기에서 켜지는 웹 기술 목록.
설치된 브라우저 빌드 버전이 Playwright와 다르면 PW_CHROMIUM · PW_WEBKIT 환경변수로 실행 파일 경로를 줄 수 있다.
"""

import argparse
import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

PAGES = [
    "/",
    "/search?q=봄봄",
    "/books/1",
    "/books/1/read?room=1",
    "/rooms",
    "/rooms/1",
    "/battles/1",
    "/teams",
    "/teams/1",
    "/me",
    "/offline",
]
DEVICES = {"chromium": "Pixel 7", "webkit": "iPhone 15"}
LAYOUT = """() => {
  const t = document.querySelector('.tabs'); const r = t && t.getBoundingClientRect();
  const over = [...document.querySelectorAll('body *')]
    .filter(e => e.getBoundingClientRect().right > innerWidth + 1 && !e.closest('.bg,.confetti'))
    .slice(0, 2).map(e => e.tagName + '.' + e.className);
  return {fits: document.documentElement.scrollWidth <= innerWidth, tabGap: r ? Math.round(innerHeight - r.bottom) : null, over};
}"""
FEATURES = """() => ({
  viewTransitions: !!document.startViewTransition, springEasing: CSS.supports('transition-timing-function','linear(0,1)'),
  scrollDriven: CSS.supports('animation-timeline','view()'), serviceWorker: 'serviceWorker' in navigator,
  webPush: 'PushManager' in window, wakeLock: 'wakeLock' in navigator, webLocks: 'locks' in navigator,
  speech: 'speechSynthesis' in window, liquidRefraction: document.documentElement.classList.contains('lg-refract')})"""


async def login(page, base: str, email: str, password: str) -> None:
    await page.goto(base + "/login")
    await page.fill("#email", email)
    await page.fill("#password", password)
    await page.click("button[type=submit]")
    await page.wait_for_url(base + "/")


async def check_engine(p, engine: str, args) -> dict:
    exe = os.environ.get(f"PW_{engine.upper()}")
    browser = await getattr(p, engine).launch(**({"executable_path": exe} if exe else {}))
    ctx = await browser.new_context(**p.devices[DEVICES[engine]], locale="ko-KR")
    page = await ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:160]))
    page.on("console", lambda m: errors.append(m.text[:160]) if m.type == "error" else None)
    await login(page, args.base, args.email, args.password)
    layout = {}
    for path in PAGES:
        await page.goto(args.base + path)
        await page.wait_for_timeout(3000 if "search" in path else 1300)
        layout[path] = await page.evaluate(LAYOUT)
        if args.shots:
            name = path.strip("/").replace("/", "_").replace("?", "_") or "home"
            await page.screenshot(path=os.path.join(args.shots, f"{engine}-{name}.png"))
    features = await page.evaluate(FEATURES)

    # 움직임 줄이기: 첫 화면 내용이 처음부터 보여야 한다
    reduced = await browser.new_context(**p.devices[DEVICES[engine]], reduced_motion="reduce")
    rp = await reduced.new_page()
    await login(rp, args.base, args.email, args.password)
    await rp.goto(args.base + "/teams", wait_until="commit")
    await rp.wait_for_selector(".content > *", state="attached")
    reduced_ok = await rp.evaluate(
        "() => [...document.querySelectorAll('.content > *')].every(e => +getComputedStyle(e).opacity === 1)"
    )
    await browser.close()

    bad = {k: v for k, v in layout.items() if not v["fits"] or v["over"]}
    return {
        "device": DEVICES[engine],
        "overflow": bad,
        "errors": errors,
        "reducedMotionVisible": reduced_ok,
        "features": features,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--email", default="seoyeon@demo.kr")
    ap.add_argument("--password", default="demo1234")
    ap.add_argument("--shots", default="")
    args = ap.parse_args()
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    async with async_playwright() as p:
        results = {engine: await check_engine(p, engine, args) for engine in DEVICES}
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = all(not r["overflow"] and not r["errors"] and r["reducedMotionVisible"] for r in results.values())
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
