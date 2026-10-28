"""이메일·비밀번호 세션 인증 (이전 Spring Security 구현의 명세를 그대로 옮김).

- 이메일은 앞뒤 공백 제거 + 소문자로 저장·조회, DB UNIQUE로 동시 가입도 차단
- 비밀번호는 BCrypt(cost 12), 8자 이상 · UTF-8 72바이트 이하
- 세션은 서명된 HttpOnly·SameSite=Lax 쿠키, 30분 동안 요청이 없으면 만료
- 로그인 시 세션을 새로 만들고(고정 공격 방지), 모든 POST는 CSRF 토큰을 검사
"""

import hmac
import secrets
import time
from dataclasses import dataclass, field

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.models import User

BCRYPT_COST = 12
MIN_PASSWORD_CHARS = 8
MAX_PASSWORD_BYTES = 72  # BCrypt가 이 이후를 버리므로 넘으면 거부
# 없는 이메일로 로그인해도 같은 시간이 걸리도록 비교에 쓰는 더미 해시
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(BCRYPT_COST))


class LoginRequired(Exception):
    """페이지 요청에서 로그인이 필요할 때 — main.py에서 /login으로 보낸다."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass
class SignupForm:
    nickname: str
    email: str
    password: str
    password_confirm: str
    errors: dict[str, str] = field(default_factory=dict)

    def validate(self) -> bool:
        self.nickname = self.nickname.strip()
        self.email = normalize_email(self.email)
        if not 1 <= len(self.nickname) <= 40:
            self.errors["nickname"] = "이름은 1~40자로 입력해 주세요"
        if "@" not in self.email or len(self.email) > 255 or self.email.startswith("@"):
            self.errors["email"] = "올바른 이메일을 입력해 주세요"
        if len(self.password) < MIN_PASSWORD_CHARS:
            self.errors["password"] = f"비밀번호는 {MIN_PASSWORD_CHARS}자 이상이어야 해요"
        elif len(self.password.encode()) > MAX_PASSWORD_BYTES:
            self.errors["password"] = "비밀번호가 너무 길어요 (최대 72바이트)"
        if self.password != self.password_confirm:
            self.errors["password_confirm"] = "비밀번호가 서로 달라요"
        return not self.errors


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_COST)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    raw = password.encode()
    if hashed is None or len(raw) > MAX_PASSWORD_BYTES:
        bcrypt.checkpw(b"x", _DUMMY_HASH)
        return False
    return bcrypt.checkpw(raw, hashed.encode())


async def create_user(session: AsyncSession, form: SignupForm) -> User | None:
    """중복 이메일이면 None (동시 가입은 UNIQUE 제약이 막는다)."""
    if await session.scalar(select(User.id).where(User.email == form.email)):
        return None
    user = User(nickname=form.nickname, email=form.email, password_hash=hash_password(form.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    ok = verify_password(password, user.password_hash if user else None)
    return user if ok else None


# --- 세션 ---


def login(request: Request, user: User) -> None:
    request.session.clear()  # 기존 세션 내용·CSRF 토큰을 버리고 새로 시작
    request.session.update({"uid": user.id, "seen": int(time.time()), "csrf": secrets.token_urlsafe(32)})


def logout(request: Request) -> None:
    request.session.clear()


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf")
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(403, "요청이 만료됐어요. 페이지를 새로고침해 주세요")


def _session_uid(request: Request) -> int | None:
    uid, seen = request.session.get("uid"), request.session.get("seen", 0)
    if uid is None:
        return None
    now = int(time.time())
    if now - seen > get_settings().session_idle_minutes * 60:
        request.session.clear()
        return None
    request.session["seen"] = now  # 요청이 있을 때마다 만료 시각을 미룬다
    return uid


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User | None:
    uid = _session_uid(request)
    return await session.get(User, uid) if uid else None


async def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise LoginRequired
    return user


async def require_api_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "로그인이 필요해요")
    return user
