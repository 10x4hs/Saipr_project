"""이메일 가입 · 로그인 (Spring Boot 인증 모듈을 FastAPI로 옮긴 것)."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    DUMMY_HASH,
    hash_password,
    normalize_email,
    validate_email,
    validate_password,
    verify_password,
)
from app.models import AVATAR_COLORS, OAuthAccount, User, new_friend_code

BIO_MAX = 160
DAILY_GOAL_RANGE = (1, 600)
YEARLY_GOAL_RANGE = (1, 365)


class AuthError(Exception):
    def __init__(self, errors: dict[str, str], status: int = 400) -> None:
        super().__init__("; ".join(errors.values()))
        self.errors = errors
        self.status = status


def validate_signup(nickname: str, email: str, password: str, password_confirm: str) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not 1 <= len(nickname.strip()) <= 40:
        errors["nickname"] = "닉네임은 1~40자로 정해 주세요."
    if msg := validate_email(email):
        errors["email"] = msg
    if msg := validate_password(password):
        errors["password"] = msg
    elif password != password_confirm:
        errors["password_confirm"] = "비밀번호가 서로 달라요."
    return errors


async def signup(
    session: AsyncSession, nickname: str, email: str, password: str, password_confirm: str
) -> User:
    email = normalize_email(email)
    if errors := validate_signup(nickname, email, password, password_confirm):
        raise AuthError(errors)
    if await session.scalar(select(User.id).where(User.email == email)):
        raise AuthError({"email": "이미 가입된 이메일이에요."}, 409)
    user = User(
        nickname=nickname.strip(),
        email=email,
        password_hash=hash_password(password),
        friend_code=await unique_friend_code(session),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as e:
        # 동시에 같은 이메일로 가입한 경우 DB UNIQUE 제약이 막는다
        await session.rollback()
        raise AuthError({"email": "이미 가입된 이메일이에요."}, 409) from e
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        verify_password(password, DUMMY_HASH)  # 응답 시간을 맞춘다
        return None
    return user if verify_password(password, user.password_hash) else None


async def oauth_user(
    session: AsyncSession, provider: str, provider_user_id: str, nickname: str, email: str | None
) -> User:
    """소셜 계정으로 로그인. 처음이면 새 사용자를 만든다.

    같은 이메일의 기존 계정에 자동으로 연결하지 않는다. 제공자가 이메일 소유를 확인하지 않았을 수 있어
    남의 계정을 가로챌 수 있기 때문이다. 이메일이 겹치면 이메일 없이 만든다.
    """
    account = await session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider, OAuthAccount.provider_user_id == provider_user_id
        )
    )
    if account:
        user = await session.get(User, account.user_id)
        if user:
            return user
        # 사용자는 지워졌는데 연결 기록만 남은 경우 — 지우고 새로 만든다 (그대로 두면 UNIQUE 위반)
        await session.delete(account)
        await session.flush()
    if email:
        email = normalize_email(email)
        if await session.scalar(select(User.id).where(User.email == email)):
            email = None
    user = User(
        nickname=(nickname or f"{provider} 사용자")[:40],
        email=email,
        friend_code=await unique_friend_code(session),
    )
    session.add(user)
    await session.flush()
    session.add(OAuthAccount(user_id=user.id, provider=provider, provider_user_id=provider_user_id))
    await session.commit()
    return user


async def unique_friend_code(session: AsyncSession) -> str:
    """아직 아무도 안 쓰는 친구 코드.

    겹칠 확률은 아주 낮지만 UNIQUE 위반으로 가입이 실패하지 않게 먼저 확인한다.
    """
    for _ in range(10):
        code = new_friend_code()
        if not await session.scalar(select(User.id).where(User.friend_code == code)):
            return code
    raise AuthError({"friend_code": "잠시 후 다시 시도해 주세요."}, 503)


def _in_range(value: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= value <= bounds[1]


async def update_profile(session: AsyncSession, user: User, changes: dict) -> User:
    """닉네임 · 소개 · 목표 · 스포일러 가드 · 아바타 색. changes에는 보낸 필드만 들어 있다.

    모두 검사한 다음에 한꺼번에 바꾼다(하나라도 틀리면 아무것도 바꾸지 않는다).
    """
    errors: dict[str, str] = {}
    apply: dict[str, object] = {}
    if "nickname" in changes:
        nickname = (changes["nickname"] or "").strip()
        if 1 <= len(nickname) <= 40:
            apply["nickname"] = nickname
        else:
            errors["nickname"] = "닉네임은 1~40자로 정해 주세요."
    if "bio" in changes:
        bio = (changes["bio"] or "").strip()
        if len(bio) <= BIO_MAX:
            apply["bio"] = bio or None
        else:
            errors["bio"] = f"소개는 {BIO_MAX}자 이하로 써 주세요."
    if "daily_goal_minutes" in changes:
        v = changes["daily_goal_minutes"]
        if isinstance(v, int) and _in_range(v, DAILY_GOAL_RANGE):
            apply["daily_goal_minutes"] = v
        else:
            errors["daily_goal_minutes"] = "하루 목표는 1~600분 사이로 정해 주세요."
    if "yearly_goal_books" in changes:
        v = changes["yearly_goal_books"]
        if isinstance(v, int) and _in_range(v, YEARLY_GOAL_RANGE):
            apply["yearly_goal_books"] = v
        else:
            errors["yearly_goal_books"] = "올해 목표는 1~365권 사이로 정해 주세요."
    if "spoiler_guard" in changes:
        if isinstance(changes["spoiler_guard"], bool):
            apply["spoiler_guard"] = changes["spoiler_guard"]
        else:
            errors["spoiler_guard"] = "스포일러 가드는 켜기 또는 끄기로 정해 주세요."
    if "avatar_color" in changes:
        color = changes["avatar_color"]
        if color is None or color in AVATAR_COLORS:
            apply["avatar_color"] = color
        else:
            errors["avatar_color"] = "준비된 색 중에서 골라 주세요."
    if errors:
        raise AuthError(errors)
    for key, value in apply.items():
        setattr(user, key, value)
    await session.commit()
    return user
