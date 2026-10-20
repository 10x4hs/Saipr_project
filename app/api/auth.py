from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    BAD_TOKEN,
    bearer_auth,
    bearer_of,
    csrf_token,
    current_user,
    login_session,
    logout_session,
    verify_csrf,
)
from app.api.schemas import MeOut, me_out
from app.db.session import get_session
from app.models import User
from app.services import auth as auth_service
from app.services import tokens as token_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"], dependencies=[Depends(verify_csrf)])
# 토큰 발급은 쿠키를 만들지 않고 응답 본문으로만 돌려주므로(다른 사이트는 읽을 수 없다) CSRF 검사가 필요 없다.
# 앱이 만료된 토큰을 붙인 채 다시 로그인해도 막히지 않도록 verify_csrf를 걸지 않는다.
token_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class SignupIn(BaseModel):
    nickname: str
    email: str
    password: str
    password_confirm: str


class LoginIn(BaseModel):
    email: str
    password: str


class SettingsIn(BaseModel):
    spoiler_guard: bool


class ProfileIn(BaseModel):
    """보낸 필드만 바꾼다. 범위 검사는 서비스가 하고 한국어 오류를 돌려준다."""

    nickname: str | None = None
    bio: str | None = None
    daily_goal_minutes: int | None = None
    yearly_goal_books: int | None = None
    spoiler_guard: bool | None = None
    avatar_color: str | None = None


class TokenOut(BaseModel):
    token: str
    user: MeOut


@router.get("/csrf")
async def get_csrf(request: Request) -> dict[str, str]:
    return {"csrf_token": csrf_token(request)}


@router.post("/signup", response_model=MeOut, status_code=201)
async def signup(body: SignupIn, request: Request, session: AsyncSession = Depends(get_session)) -> MeOut:
    user = await auth_service.signup(session, body.nickname, body.email, body.password, body.password_confirm)
    login_session(request, user)
    return me_out(user)


@router.post("/login", response_model=MeOut)
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)) -> MeOut:
    user = await auth_service.authenticate(session, body.email, body.password)
    if user is None:
        # 이메일이 틀렸는지 비밀번호가 틀렸는지 구분하지 않는다
        raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않아요.")
    login_session(request, user)
    return me_out(user)


@router.post("/logout", status_code=204)
async def logout(request: Request) -> None:
    logout_session(request)


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(current_user)) -> MeOut:
    return me_out(user)


@router.put("/me/settings", response_model=MeOut)
async def update_settings(
    body: SettingsIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> MeOut:
    user.spoiler_guard = body.spoiler_guard
    await session.commit()
    return me_out(user)


@router.put("/me/profile", response_model=MeOut)
async def update_profile(
    body: ProfileIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> MeOut:
    return me_out(await auth_service.update_profile(session, user, body.model_dump(exclude_unset=True)))


# ── 네이티브 앱 토큰 ─────────────────────────────────────────


@token_router.post("/token", response_model=TokenOut)
async def issue_token(body: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    user = await auth_service.authenticate(session, body.email, body.password)
    if user is None:
        raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않아요.")
    return TokenOut(token=await token_service.issue(session, user), user=me_out(user))


@token_router.post("/token/signup", response_model=TokenOut, status_code=201)
async def signup_token(body: SignupIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    user = await auth_service.signup(session, body.nickname, body.email, body.password, body.password_confirm)
    return TokenOut(token=await token_service.issue(session, user), user=me_out(user))


@token_router.delete("/token", status_code=204)
async def revoke_token(request: Request, session: AsyncSession = Depends(get_session)) -> None:
    found = await bearer_auth(request, session) if bearer_of(request) is not None else None
    if found is None:
        raise HTTPException(401, BAD_TOKEN)
    await token_service.revoke(session, found[0])
