import httpx

from app.core.config import Settings
from app.core.security import hash_password, verify_password
from app.services import oauth
from tests.conftest import signup

SIGNUP = {
    "nickname": "서연",
    "email": "Seo@Test.kr ",
    "password": "password123",
    "password_confirm": "password123",
}


async def csrf(c: httpx.AsyncClient) -> dict:
    return {"X-CSRF-Token": (await c.get("/api/v1/auth/csrf")).json()["csrf_token"]}


def test_password_hash_roundtrip():
    h = hash_password("비밀번호123")
    assert h.startswith("scrypt$") and "비밀번호123" not in h
    assert verify_password("비밀번호123", h)
    assert not verify_password("wrong-pass", h)
    assert not verify_password("x", None)


async def test_signup_normalizes_email_and_logs_in(api):
    async with api() as c:
        r = await c.post("/api/v1/auth/signup", json=SIGNUP, headers=await csrf(c))
        assert r.status_code == 201
        assert r.json()["email"] == "seo@test.kr"
        me = await c.get("/api/v1/auth/me")
    assert me.json()["nickname"] == "서연"


async def test_signup_validation_and_duplicate(api):
    async with api() as c:
        bad = await c.post(
            "/api/v1/auth/signup",
            json={**SIGNUP, "email": "nope", "password": "short", "password_confirm": "short"},
            headers=await csrf(c),
        )
        assert bad.status_code == 400
        assert set(bad.json()["errors"]) == {"email", "password"}

        mismatch = await c.post(
            "/api/v1/auth/signup", json={**SIGNUP, "password_confirm": "different1"}, headers=await csrf(c)
        )
        assert mismatch.json()["errors"] == {"password_confirm": "비밀번호가 서로 달라요."}

        too_long = await c.post(
            "/api/v1/auth/signup",
            json={**SIGNUP, "password": "가" * 25, "password_confirm": "가" * 25},
            headers=await csrf(c),
        )
        assert "password" in too_long.json()["errors"]  # 75바이트 > 72

        assert (await c.post("/api/v1/auth/signup", json=SIGNUP, headers=await csrf(c))).status_code == 201
    async with api() as other:
        dup = await other.post(
            "/api/v1/auth/signup", json={**SIGNUP, "email": "seo@test.kr"}, headers=await csrf(other)
        )
    assert dup.status_code == 409


async def test_login_logout_and_session_rotation(api):
    async with api() as c:
        await c.post("/api/v1/auth/signup", json=SIGNUP, headers=await csrf(c))
    async with api() as c:
        assert (await c.get("/api/v1/auth/me")).status_code == 401
        h = await csrf(c)
        before = c.cookies.get("saipr_session")
        wrong = await c.post(
            "/api/v1/auth/login", json={"email": "seo@test.kr", "password": "nope-nope"}, headers=h
        )
        assert wrong.status_code == 401
        ok = await c.post(
            "/api/v1/auth/login", json={"email": "SEO@test.kr", "password": "password123"}, headers=h
        )
        assert ok.status_code == 200
        assert c.cookies.get("saipr_session") != before  # 로그인 시 세션 교체

        # 로그인 후에는 이전 CSRF 토큰이 무효
        stale = await c.post("/api/v1/auth/logout", headers=h)
        assert stale.status_code == 403
        assert (await c.post("/api/v1/auth/logout", headers=await csrf(c))).status_code == 204
        assert (await c.get("/api/v1/auth/me")).status_code == 401


async def test_csrf_required_for_state_changes(api):
    async with api() as c:
        await signup(c)
        del c.headers["X-CSRF-Token"]
        r = await c.put("/api/v1/auth/me/settings", json={"spoiler_guard": False})
        assert r.status_code == 403
        r = await c.put("/api/v1/auth/me/settings", json={"spoiler_guard": False}, headers=await csrf(c))
        assert r.json()["spoiler_guard"] is False


def test_oauth_providers_enabled_only_with_keys():
    assert oauth.enabled_providers(Settings(_env_file=None)) == {}
    s = Settings(
        _env_file=None,
        kakao_rest_api_key="k",
        kakao_login_enabled=True,
        google_client_id="g",
        google_client_secret="s",
    )
    assert set(oauth.enabled_providers(s)) == {"kakao", "google"}
    url = oauth.authorize_url(oauth.enabled_providers(s)["google"], "http://x/cb", "st")
    assert "state=st" in url and "client_id=g" in url


def test_oauth_profile_parsing():
    k = oauth.parse_profile(
        "kakao", {"id": 7, "kakao_account": {"profile": {"nickname": "준호"}, "email": "j@k.kr"}}
    )
    assert (k.id, k.nickname, k.email) == ("7", "준호", "j@k.kr")
    g = oauth.parse_profile("google", {"sub": "s1", "name": "G", "email": "g@x.kr", "email_verified": False})
    assert g.email is None  # 확인 안 된 이메일은 쓰지 않는다
    n = oauth.parse_profile("naver", {"response": {"id": "n1", "nickname": "네", "email": "n@x.kr"}})
    assert n.id == "n1"


async def test_oauth_callback_rejects_bad_state(api):
    async with api() as c:
        r = await c.get("/auth/google/callback", params={"code": "c", "state": "forged"})
    assert r.status_code in (303, 404)


def test_hosting_postgres_url_uses_async_driver():
    s = Settings(_env_file=None, database_url="postgres://u:p@h:5432/d")
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert Settings(_env_file=None, database_url="sqlite+aiosqlite:///x.db").database_url.startswith("sqlite")
