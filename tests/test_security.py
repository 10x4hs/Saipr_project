"""PR #6 리뷰에서 나온 결함들의 회귀 테스트."""

import io
import re
import zipfile

import pytest

from app.services.uploads import parse_upload
from app.sources.base import SourceError
from tests.conftest import csrf_of, signup
from tests.test_api import upstream


def token_of(html: str) -> str:
    return re.search(r'<meta name="csrf" content="([^"]+)"', html).group(1)


async def _open(c, page: str = "긴글") -> tuple[str, dict]:
    url = (await c.get(f"/open/wikisource/{page}")).headers["location"]
    return url.rsplit("/", 1)[1], {"X-CSRF-Token": token_of((await c.get(url)).text)}


async def test_preopening_pages_does_not_skip_the_wait(api, clock):
    """H1: 여러 쪽을 미리 펼쳐 두고 한 번 기다린 뒤 줄줄이 인정받을 수 없다."""
    async with api(upstream) as c:
        await signup(c)
        book, h = await _open(c)
        for i in range(3):  # 0~2쪽을 한꺼번에 펼친다
            await c.put(f"/api/v1/books/{book}/progress", json={"chunk_index": i}, headers=h)
        clock(10)
        results = [
            (
                await c.put(
                    f"/api/v1/books/{book}/progress", json={"chunk_index": i, "verified": True}, headers=h
                )
            ).json()
            for i in range(3)
        ]
    assert results[0]["verified_chunk"] == 0
    assert results[2]["verified_chunk"] == 0  # 1·2쪽은 0쪽을 다 읽은 뒤에 다시 펼쳐야 한다


async def test_failed_check_does_not_restart_the_timer(api, clock):
    """H2: 너무 일찍 보낸 '다 읽음'이 펼친 시각을 덮어쓰지 않는다."""
    async with api(upstream) as c:
        await signup(c)
        book, h = await _open(c)
        await c.put(f"/api/v1/books/{book}/progress", json={"chunk_index": 0}, headers=h)
        clock(0.01)
        early = await c.put(
            f"/api/v1/books/{book}/progress", json={"chunk_index": 0, "verified": True}, headers=h
        )
        clock(10)
        later = await c.put(
            f"/api/v1/books/{book}/progress", json={"chunk_index": 0, "verified": True}, headers=h
        )
    assert early.json()["verified_chunk"] == -1 and later.json()["verified_chunk"] == 0


def test_zip_bomb_epub_is_refused():
    """H3: 압축을 풀면 엄청 커지는 EPUB은 열기 전에 거절."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml", "<container/>")
        z.writestr("OEBPS/huge.xhtml", b"\0" * (90 * 1024 * 1024))
    with pytest.raises(SourceError, match="너무 커요"):
        parse_upload("bomb.epub", buf.getvalue(), max_bytes=50 * 1024 * 1024)


@pytest.mark.parametrize("target", ["/\\evil.com", "//evil.com", "https://evil.com", "/%5Cevil.com"])
async def test_login_next_stays_on_site(api, target):
    """M1: 로그인 뒤 다른 사이트로 보내지 않는다."""
    from urllib.parse import unquote

    async with api(upstream) as c:
        await signup(c, email="n@example.com")
        c.cookies.clear()
        token = await csrf_of(c, "/login")
        r = await c.post(
            "/login",
            data={
                "email": "n@example.com",
                "password": "password123",
                "next": unquote(target),
                "csrf": token,
            },
        )
    assert r.headers["location"] == "/"


async def test_logout_invalidates_copied_cookie(api):
    """L2: 로그아웃하면 그 전에 복사해 둔 세션 쿠키도 더는 통하지 않는다."""
    async with api(upstream) as c, api(upstream) as thief:
        await signup(c)
        thief.cookies.update(dict(c.cookies))
        assert (await thief.get("/me")).status_code == 200
        me = await c.get("/me")
        await c.post("/logout", data={"csrf": me.text.split('name="csrf" value="')[1].split('"')[0]})
        after = await thief.get("/me")
    assert after.status_code == 303


async def test_avatar_only_visible_to_self_and_race_mates(api):
    """L3: 같은 대결방이 아닌 사람의 사진은 받을 수 없다."""
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 500
    async with api(upstream) as a, api(upstream) as stranger:
        await signup(a, email="a@example.com")
        await signup(stranger, email="s@example.com")
        me = await a.get("/me")
        token = me.text.split('name="csrf" value="')[1].split('"')[0]
        await a.post(
            "/me/profile",
            data={"csrf": token, "nickname": "에이"},
            files={"photo": ("a.jpg", jpeg, "image/jpeg")},
        )
        src = (await a.get("/me")).text.split('<span class="avatar xl"><img src="')[1].split('"')[0]
        mine = await a.get(src)
        theirs = await stranger.get(src)
    assert mine.status_code == 200 and theirs.status_code == 404


async def test_security_headers_on_every_page(api):
    async with api(upstream) as c:
        r = await c.get("/login")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert "camera=()" in r.headers["permissions-policy"]


async def test_login_pauses_after_repeated_wrong_passwords(api):
    async with api(upstream) as c:
        await signup(c, email="brute@example.com")
        c.cookies.clear()
        token = await csrf_of(c, "/login")
        for _ in range(5):
            await c.post(
                "/login", data={"email": "brute@example.com", "password": "wrongpass1", "csrf": token}
            )
        blocked = await c.post(
            "/login", data={"email": "brute@example.com", "password": "password123", "csrf": token}
        )
    assert blocked.status_code == 200 and "10분 뒤에" in blocked.text  # 맞는 비밀번호여도 잠시 멈춘다
