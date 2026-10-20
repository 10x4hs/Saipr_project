"""기기 저장소 — 로그인 토큰 · 설정 · 받아 둔 책 본문 · 보내지 못한 읽은 기록.

Flet의 SharedPreferences(안드로이드 SharedPreferences, iOS NSUserDefaults, 웹 localStorage)에 JSON으로 저장한다.
본문은 쪽(청크)마다 따로 저장해서, 한 번 연 쪽은 비행기 모드에서도 다시 읽힌다.
"""

from __future__ import annotations

import json
from typing import Any

PREFIX = "saipr."


class Store:
    def __init__(self, prefs: Any) -> None:
        self.prefs = prefs  # ft.SharedPreferences (테스트에서는 같은 메서드를 가진 가짜)
        self._mem: dict[str, Any] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        if key in self._mem:
            return self._mem[key]
        try:
            raw = await self.prefs.get(PREFIX + key)
        except Exception:  # 저장소를 쓸 수 없는 환경 — 메모리로만 동작
            raw = None
        value = default
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except ValueError:
                value = default
        self._mem[key] = value
        return value

    async def set(self, key: str, value: Any) -> None:
        self._mem[key] = value
        try:
            await self.prefs.set(PREFIX + key, json.dumps(value, ensure_ascii=False))
        except Exception:
            pass

    async def remove(self, key: str) -> None:
        self._mem.pop(key, None)
        try:
            await self.prefs.remove(PREFIX + key)
        except Exception:
            pass

    # ── 본문 캐시 ─────────────────────────────────────
    async def chunk(self, book_id: int, index: int) -> dict | None:
        return await self.get(f"chunk.{book_id}.{index}")

    async def save_chunk(self, book_id: int, index: int, data: dict) -> None:
        await self.set(f"chunk.{book_id}.{index}", data)
        books = await self.get("offline_books", [])
        if book_id not in books:
            await self.set("offline_books", [*books, book_id])
