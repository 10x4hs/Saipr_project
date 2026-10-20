"""함께읽기 앱 진입점.

    flet run src/main.py          # 데스크톱 창으로 실행
    flet run --web src/main.py    # 브라우저로 실행
    flet build apk                # 안드로이드 설치 파일 (JDK 17 필요, Flutter는 자동 설치)
"""

import logging

import flet as ft

from saipr.app import App

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main(page: ft.Page) -> None:
    page.padding = 0
    page.window.width, page.window.height = 420, 880  # 데스크톱: 폰 크기 창
    page.window.min_width = 360
    await App(page).start()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
