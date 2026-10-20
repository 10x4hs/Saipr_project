"""웹 푸시 구독 API. 브라우저가 공개 키로 구독하고, 구독 정보를 여기에 맡긴다."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, verify_csrf
from app.db.session import get_session
from app.models import User
from app.services import notifications, push

router = APIRouter(prefix="/api/v1/push", tags=["push"], dependencies=[Depends(verify_csrf)])


class Keys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=1000, pattern=r"^https://")
    keys: Keys


class EndpointIn(BaseModel):
    endpoint: str = Field(max_length=1000)


@router.get("/key")
async def vapid_key() -> dict[str, str]:
    return {"public_key": push.public_key()}


@router.post("/subscribe", status_code=204)
async def subscribe(
    body: SubscriptionIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> None:
    await push.subscribe(session, user.id, body.endpoint, body.keys.p256dh, body.keys.auth)


@router.post("/unsubscribe", status_code=204)
async def unsubscribe(
    body: EndpointIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> None:
    await push.unsubscribe(session, user.id, body.endpoint)


@router.post("/test", status_code=202)
async def test_push(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """시연용: 나에게 알림 하나를 보낸다 (알림함 + 실시간 + 웹 푸시). 하루 5건·방해 금지 규칙은 그대로."""
    n = await notifications.notify(session, user.id, "test", "푸시 알림이 잘 도착했어요 📚", "/me")
    await session.commit()
    return {"queued": n is not None, "subscriptions": len(await push.targets_of(session, user.id))}
