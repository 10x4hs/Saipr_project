"""읽기방 채팅 API (네이티브 앱)."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, verify_csrf
from app.api.schemas import UserMini, user_mini
from app.db.session import get_session
from app.models import RoomMessage, User
from app.services import chat as chat_service

router = APIRouter(prefix="/api/v1", tags=["rooms"], dependencies=[Depends(verify_csrf)])


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)  # 앞뒤 공백을 뺀 뒤 1~500자인지는 서비스가 본다


class MessageOut(BaseModel):
    id: int
    user: UserMini
    body: str
    created_at: datetime


def message_out(m: RoomMessage, author: User) -> MessageOut:
    return MessageOut(id=m.id, user=user_mini(author), body=m.body, created_at=m.created_at)


@router.get("/rooms/{room_id}/messages", response_model=list[MessageOut])
async def list_messages(
    room_id: int,
    before: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=chat_service.PAGE_MAX),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """오래된 → 새 순. 더 앞의 메시지는 첫 항목의 id를 before로."""
    room = await chat_service.member_room(session, room_id, user)
    return [message_out(m, u) for m, u in await chat_service.history(session, room, before, limit)]


@router.post("/rooms/{room_id}/messages", response_model=MessageOut, status_code=201)
async def post_message(
    room_id: int,
    body: MessageIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    room = await chat_service.member_room(session, room_id, user)
    return message_out(await chat_service.post(session, room, user, body.body), user)
