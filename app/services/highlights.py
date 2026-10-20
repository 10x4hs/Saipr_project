"""개인 밑줄 · 메모 (docs/plans/2026-10-20-native-app-design.md '밑줄 · 메모').

- 배틀 밑줄과 같은 테이블을 쓰지만 battle_id가 NULL인 것만 여기서 다룬다(배틀 결과를 바꾸지 못하게).
- 밑줄 문장은 그 청크 본문에 실제로 있어야 하고(공백은 하나로 맞춰 비교),
  읽은 위치 + 1 청크까지만 그을 수 있다.
- visibility=friends는 나를 팔로우한 사람에게 보이고 피드에 highlight 활동으로 남는다.
  private로 바꾸거나 지우면 피드에서도 지운다.
- 친구 밑줄 목록은 스포일러 가드를 따른다. 내 위치보다 뒤는 개수만 알려 준다.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models import Book, BookChunk, Follow, Highlight, User
from app.services import activity, library

COLORS = ("yellow", "green", "blue", "pink")
VISIBILITIES = ("private", "friends")
QUOTE_MAX = 500
NOTE_MAX = 280
LIST_MAX = 500


class HighlightError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def normalize(text: str) -> str:
    return " ".join(text.split())


def _check_color(color: str) -> None:
    if color not in COLORS:
        raise HighlightError("색은 yellow · green · blue · pink 중에서 골라 주세요.")


def _check_visibility(visibility: str) -> None:
    if visibility not in VISIBILITIES:
        raise HighlightError("공개 범위는 private 또는 friends로 정해 주세요.")


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    note = note.strip()
    if len(note) > NOTE_MAX:
        raise HighlightError(f"메모는 {NOTE_MAX}자 이하로 써 주세요.")
    return note or None


async def create(
    session: AsyncSession,
    user: User,
    book: Book,
    chunk_index: int,
    anchor: int,
    quote: str,
    note: str | None = None,
    color: str = "yellow",
    visibility: str = "private",
    now: datetime | None = None,
) -> Highlight:
    now = now or utcnow()
    if not book.has_fulltext:
        raise HighlightError("앱 안에서 읽는 책에만 밑줄을 그을 수 있어요.")
    if not 0 <= chunk_index < book.total_chunks:
        raise HighlightError("위치가 책 범위를 벗어났어요.")
    if not 0 <= anchor < 1000:
        raise HighlightError("문단 번호가 올바르지 않아요.")
    _check_color(color)
    _check_visibility(visibility)
    quote = normalize(quote)
    if not 1 <= len(quote) <= QUOTE_MAX:
        raise HighlightError(f"밑줄 문장은 1~{QUOTE_MAX}자예요.")
    note = _clean_note(note)
    entry = await library.get_entry(session, user.id, book.id)
    if chunk_index > library.position_of(entry, book) + 1:
        raise HighlightError("아직 읽지 않은 위치에는 밑줄을 그을 수 없어요.", 403)
    text = await session.scalar(
        select(BookChunk.text).where(BookChunk.book_id == book.id, BookChunk.chunk_index == chunk_index)
    )
    if text is None or quote not in normalize(text):
        raise HighlightError("밑줄 문장이 본문에 없어요.")
    h = Highlight(
        user_id=user.id,
        book_id=book.id,
        battle_id=None,
        chunk_index=chunk_index,
        anchor=anchor,
        quote=quote,
        comment=note,
        color=color,
        visibility=visibility,
        created_at=now,
    )
    session.add(h)
    await session.flush()
    if visibility == "friends":
        await activity.highlight_shared(session, user.id, book.id, h.id, quote, note, chunk_index, now)
    await session.commit()
    return h


async def get_own(session: AsyncSession, user: User, highlight_id: int) -> Highlight:
    h = await session.get(Highlight, highlight_id)
    # 남의 밑줄인지 없는 밑줄인지 구분하지 않는다(비공개 밑줄의 존재도 알려 주지 않는다)
    if h is None or h.user_id != user.id or h.battle_id is not None:
        raise HighlightError("밑줄을 찾을 수 없어요.", 404)
    return h


async def update(session: AsyncSession, user: User, highlight_id: int, changes: dict) -> Highlight:
    h = await get_own(session, user, highlight_id)
    if "color" in changes:
        _check_color(changes["color"])
    if "visibility" in changes:
        _check_visibility(changes["visibility"])
    note = _clean_note(changes["note"]) if "note" in changes else h.comment
    if "color" in changes:
        h.color = changes["color"]
    if "visibility" in changes:
        h.visibility = changes["visibility"]
    h.comment = note
    if h.visibility == "friends":
        await activity.highlight_shared(session, user.id, h.book_id, h.id, h.quote, h.comment, h.chunk_index)
    else:
        await activity.highlight_hidden(session, user.id, h.id)
    await session.commit()
    return h


async def remove(session: AsyncSession, user: User, highlight_id: int) -> None:
    h = await get_own(session, user, highlight_id)
    await activity.highlight_hidden(session, user.id, h.id)
    await session.delete(h)
    await session.commit()


async def mine(session: AsyncSession, user: User, book_id: int | None = None) -> list[tuple[Highlight, Book]]:
    q = (
        select(Highlight, Book)
        .join(Book, Book.id == Highlight.book_id)
        .where(Highlight.user_id == user.id, Highlight.battle_id.is_(None))
    )
    if book_id is not None:
        q = q.where(Highlight.book_id == book_id)
    q = q.order_by(Highlight.id.desc()).limit(LIST_MAX)
    return [(h, b) for h, b in (await session.execute(q)).all()]


@dataclass(slots=True)
class FriendsHighlights:
    position: int
    visible: list[tuple[Highlight, User]] = field(default_factory=list)
    locked_total: int = 0


async def of_friends(session: AsyncSession, viewer: User, book: Book) -> FriendsHighlights:
    """내가 팔로우한 사람들의 친구 공개 밑줄. 스포일러 가드를 켰으면 내 위치보다 뒤는 개수만."""
    position = library.position_of(await library.get_entry(session, viewer.id, book.id), book)
    result = FriendsHighlights(position=position)
    authors = select(Follow.followee_id).where(Follow.follower_id == viewer.id)
    cond = [
        Highlight.book_id == book.id,
        Highlight.battle_id.is_(None),
        Highlight.visibility == "friends",
        Highlight.user_id.in_(authors),
    ]
    if viewer.spoiler_guard:
        result.locked_total = int(
            await session.scalar(
                select(func.count()).select_from(Highlight).where(*cond, Highlight.chunk_index > position)
            )
            or 0
        )
        cond.append(Highlight.chunk_index <= position)
    rows = await session.execute(
        select(Highlight, User)
        .join(User, User.id == Highlight.user_id)
        .where(*cond)
        .order_by(Highlight.chunk_index, Highlight.anchor, Highlight.id)
        .limit(LIST_MAX)
    )
    result.visible = [(h, u) for h, u in rows.all()]
    return result
