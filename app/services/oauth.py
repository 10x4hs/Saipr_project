"""카카오 · 구글 · 네이버 OAuth 2.0 (PRD AUTH-01). 키가 있는 제공자만 켜진다.

Authlib 없이 httpx로 Authorization Code 흐름을 직접 구현한다. 흐름은 세 단계뿐이다.
1) authorize_url: state(위조 방지 난수)를 세션에 저장하고 제공자 로그인 화면으로 보낸다.
2) 콜백에서 state를 확인하고 code를 access token으로 바꾼다.
3) token으로 사용자 정보를 받아 (provider, id, 닉네임, 이메일)로 정리한다.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    label: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    client_id: str
    client_secret: str | None


@dataclass(frozen=True, slots=True)
class Profile:
    provider: str
    id: str
    nickname: str
    email: str | None


def enabled_providers(settings: Settings) -> dict[str, Provider]:
    out: dict[str, Provider] = {}
    if settings.kakao_login_enabled and settings.kakao_rest_api_key:
        out["kakao"] = Provider(
            "kakao",
            "카카오",
            "https://kauth.kakao.com/oauth/authorize",
            "https://kauth.kakao.com/oauth/token",
            "https://kapi.kakao.com/v2/user/me",
            "profile_nickname account_email",
            settings.kakao_rest_api_key,
            settings.kakao_client_secret,
        )
    if settings.google_client_id and settings.google_client_secret:
        out["google"] = Provider(
            "google",
            "Google",
            "https://accounts.google.com/o/oauth2/v2/auth",
            "https://oauth2.googleapis.com/token",
            "https://openidconnect.googleapis.com/v1/userinfo",
            "openid email profile",
            settings.google_client_id,
            settings.google_client_secret,
        )
    if settings.naver_login_enabled and settings.naver_client_id and settings.naver_client_secret:
        out["naver"] = Provider(
            "naver",
            "네이버",
            "https://nid.naver.com/oauth2.0/authorize",
            "https://nid.naver.com/oauth2.0/token",
            "https://openapi.naver.com/v1/nid/me",
            "",
            settings.naver_client_id,
            settings.naver_client_secret,
        )
    return out


def redirect_uri(settings: Settings, provider: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/auth/{provider}/callback"


def authorize_url(p: Provider, redirect: str, state: str) -> str:
    params = {"response_type": "code", "client_id": p.client_id, "redirect_uri": redirect, "state": state}
    if p.scope:
        params["scope"] = p.scope
    return f"{p.authorize_url}?{urlencode(params)}"


async def exchange_code(client: httpx.AsyncClient, p: Provider, code: str, redirect: str, state: str) -> str:
    data = {
        "grant_type": "authorization_code",
        "client_id": p.client_id,
        "code": code,
        "redirect_uri": redirect,
        "state": state,
    }
    if p.client_secret:
        data["client_secret"] = p.client_secret
    resp = await client.post(p.token_url, data=data, headers={"Accept": "application/json"})
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise httpx.HTTPError("no access_token in token response")
    return token


def parse_profile(provider: str, data: dict[str, Any]) -> Profile:
    if provider == "kakao":
        account = data.get("kakao_account") or {}
        nickname = (account.get("profile") or {}).get("nickname") or (data.get("properties") or {}).get(
            "nickname"
        )
        return Profile("kakao", str(data["id"]), nickname or "", account.get("email"))
    if provider == "google":
        email = data.get("email") if data.get("email_verified") else None
        return Profile("google", str(data["sub"]), data.get("name") or "", email)
    if provider == "naver":
        r = data.get("response") or {}
        return Profile("naver", str(r["id"]), r.get("nickname") or r.get("name") or "", r.get("email"))
    raise ValueError(provider)


async def fetch_profile(client: httpx.AsyncClient, p: Provider, token: str) -> Profile:
    resp = await client.get(p.userinfo_url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return parse_profile(p.name, resp.json())
