from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import csrf_token, current_user, login_session, logout_session, verify_csrf
from app.db.session import get_session
from app.models import User
from app.services import auth as auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"], dependencies=[Depends(verify_csrf)])


class SignupIn(BaseModel):
    nickname: str
    email: str
    password: str
    password_confirm: str


class LoginIn(BaseModel):
    email: str
    password: str


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    email: str | None
    spoiler_guard: bool


class SettingsIn(BaseModel):
    spoiler_guard: bool


@router.get("/csrf")
async def get_csrf(request: Request) -> dict[str, str]:
    return {"csrf_token": csrf_token(request)}


@router.post("/signup", response_model=MeOut, status_code=201)
async def signup(body: SignupIn, request: Request, session: AsyncSession = Depends(get_session)) -> User:
    user = await auth_service.signup(session, body.nickname, body.email, body.password, body.password_confirm)
    login_session(request, user)
    return user


@router.post("/login", response_model=MeOut)
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)) -> User:
    user = await auth_service.authenticate(session, body.email, body.password)
    if user is None:
        # 이메일이 틀렸는지 비밀번호가 틀렸는지 구분하지 않는다
        raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않아요.")
    login_session(request, user)
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request) -> None:
    logout_session(request)


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(current_user)) -> User:
    return user


@router.put("/me/settings", response_model=MeOut)
async def update_settings(
    body: SettingsIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> User:
    user.spoiler_guard = body.spoiler_guard
    await session.commit()
    return user
