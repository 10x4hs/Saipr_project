"""서버 API 클라이언트. 앱의 모든 네트워크 요청은 여기를 지난다.

- 로그인하면 받은 토큰을 `Authorization: Bearer`로 붙인다 (쿠키를 쓰지 않으므로 CSRF도 필요 없다).
- 서버가 보낸 한국어 오류 메시지(`detail`)를 그대로 ApiError로 올린다 — 화면은 그 문장을 보여 주면 된다.
- 네트워크가 끊긴 것(Offline)과 서버가 거절한 것(ApiError)을 구분해서, 화면이 '다시 시도'와 '안내'를 다르게 할 수 있다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ApiError(Exception):
    """서버가 요청을 거절했다 (4xx/5xx). message는 사용자에게 보여 줄 문장."""

    def __init__(self, message: str, status: int, errors: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.errors = errors or {}


class Offline(Exception):
    """서버에 닿지 못했다 (연결 실패·시간 초과)."""

    def __init__(self, message: str = "서버에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.") -> None:
        super().__init__(message)
        self.message = message


def normalize_base(url: str) -> str:
    """사용자가 입력한 서버 주소를 정리한다: 공백 제거, 스킴 보충, 끝 슬래시 제거."""
    url = url.strip()
    if not url:
        return url
    if "://" not in url:
        url = "http://" + url
    return url.rstrip("/")


@dataclass
class Api:
    base_url: str
    token: str | None = None
    transport: httpx.AsyncBaseTransport | None = None  # 테스트에서 MockTransport를 끼운다

    def __post_init__(self) -> None:
        self.base_url = normalize_base(self.base_url)
        self._client: httpx.AsyncClient | None = None

    # ── 연결 ─────────────────────────────────────────
    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=TIMEOUT, transport=self.transport, follow_redirects=False
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def set_base(self, url: str) -> None:
        self.base_url = normalize_base(url)
        if self._client is not None:
            asyncio.ensure_future(self._client.aclose())
            self._client = None

    def ws_url(self, path: str) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.split("://", 1)[1]
        sep = "&" if "?" in path else "?"
        return f"{scheme}://{host}{path}{sep}token={self.token}" if self.token else f"{scheme}://{host}{path}"

    def absolute(self, path: str | None) -> str | None:
        if not path:
            return None
        return path if path.startswith("http") else f"{self.base_url}{path}"

    # ── 요청 ─────────────────────────────────────────
    async def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            r = await self._http().request(method, "/api/v1" + path, json=json, params=params, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            raise Offline() from e
        except httpx.HTTPError as e:
            raise Offline(f"요청을 보내지 못했어요 ({type(e).__name__})") from e
        if r.status_code == 204:
            return None
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, list):  # FastAPI 검증 오류
                detail = "입력한 값을 다시 확인해 주세요."
            errors = body.get("errors") if isinstance(body, dict) else None
            raise ApiError(detail or _status_message(r.status_code), r.status_code, errors)
        return body

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params={k: v for k, v in params.items() if v is not None} or None)

    async def post(self, path: str, json: Any = None) -> Any:
        return await self.request("POST", path, json=json)

    async def put(self, path: str, json: Any = None) -> Any:
        return await self.request("PUT", path, json=json)

    async def patch(self, path: str, json: Any = None) -> Any:
        return await self.request("PATCH", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)

    # ── 자주 쓰는 묶음 ────────────────────────────────
    async def health(self) -> bool:
        try:
            r = await self._http().get("/health", timeout=4.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def login(self, email: str, password: str) -> dict:
        data = await self.post("/auth/token", {"email": email, "password": password})
        self.token = data["token"]
        return data["user"]

    async def signup(self, nickname: str, email: str, password: str, password_confirm: str) -> dict:
        data = await self.post(
            "/auth/token/signup",
            {"nickname": nickname, "email": email, "password": password, "password_confirm": password_confirm},
        )
        self.token = data["token"]
        return data["user"]

    async def logout(self) -> None:
        try:
            await self.delete("/auth/token")
        except (ApiError, Offline):
            pass  # 서버에 못 닿아도 이 기기에서는 로그아웃한다
        self.token = None


def _status_message(status: int) -> str:
    return {
        401: "다시 로그인해 주세요.",
        403: "권한이 없어요.",
        404: "찾을 수 없어요.",
        409: "이미 처리된 요청이에요.",
        410: "만료됐어요.",
        429: "잠시 후 다시 시도해 주세요.",
    }.get(status, "서버에 문제가 생겼어요. 잠시 후 다시 시도해 주세요." if status >= 500 else "요청을 처리하지 못했어요.")
