"""개인 밑줄 · 메모 API (네이티브 앱)."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_book, verify_csrf
from app.api.schemas import HighlightOut, MyHighlightOut, book_card, highlight_out
from app.db.session import get_session
from app.models import Book, User
from app.services import catalog
from app.services import highlights as highlight_service
from app.services import library as lib

router = APIRouter(prefix="/api/v1", tags=["highlights"], dependencies=[Depends(verify_csrf)])

Color = Literal["yellow", "green", "blue", "pink"]
Visibility = Literal["private", "friends"]


class HighlightIn(BaseModel):
    chunk_index: int = Field(ge=0)
    anchor: int = Field(0, ge=0, lt=1000)
    quote: str = Field(min_length=1, max_length=2000)  # 공백을 줄인 뒤 500자 이하인지는 서비스가 본다
    note: str | None = Field(None, max_length=2000)
    color: Color = "yellow"
    visibility: Visibility = "private"


class HighlightPatch(BaseModel):
    note: str | None = Field(None, max_length=2000)
    color: Color | None = None
    visibility: Visibility | None = None


class FriendsHighlightsOut(BaseModel):
    position: int
    visible: list[HighlightOut]
    locked_total: int


@router.post("/books/{book_id}/highlights", response_model=HighlightOut, status_code=201)
async def create_highlight(
    body: HighlightIn,
    book: Book = Depends(get_book),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    h = await highlight_service.create(
        session, user, book, body.chunk_index, body.anchor, body.quote, body.note, body.color, body.visibility
    )
    return highlight_out(h, user)


@router.get("/books/{book_id}/highlights", response_model=FriendsHighlightsOut)
async def book_highlights(
    scope: Literal["friends", "mine"] = "friends",
    book: Book = Depends(get_book),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """scope=friends: 내가 팔로우한 사람들의 친구 공개 밑줄(스포일러 가드 적용).
    scope=mine: 이 책의 내 밑줄."""
    if scope == "mine":
        mine = sorted(
            await highlight_service.mine(session, user, book.id), key=lambda r: (r[0].chunk_index, r[0].id)
        )
        position = lib.position_of(await lib.get_entry(session, user.id, book.id), book)
        return FriendsHighlightsOut(
            position=position, visible=[highlight_out(h, user) for h, _ in mine], locked_total=0
        )
    f = await highlight_service.of_friends(session, user, book)
    return FriendsHighlightsOut(
        position=f.position, visible=[highlight_out(h, u) for h, u in f.visible], locked_total=f.locked_total
    )


@router.get("/me/highlights", response_model=list[MyHighlightOut])
async def my_highlights(
    book_id: int | None = Query(None, ge=1),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = await highlight_service.mine(session, user, book_id)
    readers = await catalog.readers_counts(session, {b.id for _, b in rows})
    return [
        MyHighlightOut(**highlight_out(h, user).model_dump(), book=book_card(b, readers[b.id]))
        for h, b in rows
    ]


@router.patch("/highlights/{highlight_id}", response_model=HighlightOut)
async def update_highlight(
    highlight_id: int,
    body: HighlightPatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    changes = body.model_dump(exclude_unset=True)
    # color · visibility에 null을 보내면 '바꾸지 않음'으로 본다. note는 null이면 메모를 지운다
    changes = {k: v for k, v in changes.items() if v is not None or k == "note"}
    return highlight_out(await highlight_service.update(session, user, highlight_id, changes), user)


@router.delete("/highlights/{highlight_id}", status_code=204)
async def delete_highlight(
    highlight_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    await highlight_service.remove(session, user, highlight_id)
