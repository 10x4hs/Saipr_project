"""DB 스키마 — docs/PRD.md 10장 데이터 모델과 1:1 대응."""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# SQLite(테스트)에서는 BIGINT PK가 자동증가하지 않으므로 INTEGER로 대체
BigId = BigInteger().with_variant(Integer, "sqlite")


def _enum(e: type[enum.Enum]) -> Enum:
    return Enum(e, native_enum=False, length=20, values_callable=lambda x: [m.value for m in x])


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Shelf(enum.StrEnum):
    WANT = "want"
    READING = "reading"
    DONE = "done"


class RoomMode(enum.StrEnum):
    SYNC = "sync"
    ASYNC = "async"


class ReactionKind(enum.StrEnum):
    EMOJI = "emoji"
    COMMENT = "comment"


class BattleType(enum.StrEnum):
    PAGE_RACE = "page_race"
    HIGHLIGHT_BATTLE = "highlight_battle"


class BattleStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    FINISHED = "finished"


class ChallengePeriod(enum.StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    ONCE = "once"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    # BCrypt 해시. 소셜 로그인만 쓰는 계정은 비어 있다
    password_hash: Mapped[str | None] = mapped_column(String(60))
    # 화면 꾸미기 {"mode": "auto|light|dark", "bg": "<배경 id>", "accent": "<색 id>"} — 모든 기기 공통
    settings: Mapped[dict | None] = mapped_column(JSON)
    # 프로필 사진 — 브라우저에서 256px JPEG로 줄여 올린 것 (수십 KB)
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _now()


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_user_id: Mapped[str] = mapped_column(String(255))


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(512))
    isbn13: Mapped[str | None] = mapped_column(String(13), index=True)
    title: Mapped[str] = mapped_column(String(500))
    author: Mapped[str | None] = mapped_column(String(300))
    cover_url: Mapped[str | None] = mapped_column(String(1000))
    language: Mapped[str | None] = mapped_column(String(10))
    # 퍼블릭 도메인 화이트리스트 소스에서만 true (app/services/search.py FULLTEXT_SOURCES)
    has_fulltext: Mapped[bool] = mapped_column(Boolean, default=False)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    # 사용자가 올린 개인 파일(source="upload")만 채운다. 본문은 올린 사람만 열 수 있다.
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # 정규화한 본문의 SHA-256 — 서로 다른 사람이 올린 같은 책을 알아보는 데 쓴다.
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)

    chunks: Mapped[list["BookChunk"]] = relationship(
        back_populates="book", order_by="BookChunk.chunk_index", cascade="all, delete-orphan"
    )


class BookChunk(Base):
    """'페이지'를 대체하는 공통 위치 단위. 퍼블릭 도메인 본문만 저장한다."""

    __tablename__ = "book_chunks"
    __table_args__ = (UniqueConstraint("book_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)

    book: Mapped[Book] = relationship(back_populates="chunks")


class LibraryEntry(Base):
    __tablename__ = "library_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id"),
        CheckConstraint("progress_pct BETWEEN 0 AND 100", name="progress_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    shelf: Mapped[Shelf] = mapped_column(_enum(Shelf), default=Shelf.WANT)
    progress_pct: Mapped[int] = mapped_column(SmallInteger, default=0)
    # 체류시간 검증을 통과한 최대 청크 인덱스 (-1 = 아직 없음). 트래커 모드는 사용 안 함
    verified_chunk: Mapped[int] = mapped_column(Integer, default=-1)
    # 마지막으로 펼친 청크 — 이어 읽기 위치
    current_chunk: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReadingEvent(Base):
    __tablename__ = "reading_events"
    __table_args__ = (Index("ix_reading_events_user_book", "user_id", "book_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    dwell_ms: Mapped[int] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(80))
    mode: Mapped[RoomMode] = mapped_column(_enum(RoomMode), default=RoomMode.ASYNC)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class RoomMember(Base):
    __tablename__ = "room_members"

    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = _now()


class Reaction(Base):
    __tablename__ = "reactions"
    __table_args__ = (Index("ix_reactions_book_chunk", "book_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[int] = mapped_column(SmallInteger, default=0)  # 청크 내 문단 번호
    kind: Mapped[ReactionKind] = mapped_column(_enum(ReactionKind))
    body: Mapped[str] = mapped_column(String(280))
    created_at: Mapped[datetime] = _now()


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Battle(Base):
    __tablename__ = "battles"
    __table_args__ = (CheckConstraint("team_a_id <> team_b_id", name="distinct_teams"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[BattleType] = mapped_column(_enum(BattleType))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    team_a_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[BattleStatus] = mapped_column(_enum(BattleStatus), default=BattleStatus.SCHEDULED)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    battle_id: Mapped[int | None] = mapped_column(ForeignKey("battles.id", ondelete="SET NULL"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[int] = mapped_column(SmallInteger, default=0)
    quote: Mapped[str] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(String(280))
    created_at: Mapped[datetime] = _now()


class HighlightVote(Base):
    """복합 PK로 1인 1표(하이라이트당)를 DB 수준에서 강제."""

    __tablename__ = "highlight_votes"

    highlight_id: Mapped[int] = mapped_column(
        ForeignKey("highlights.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    title: Mapped[str] = mapped_column(String(100))
    condition: Mapped[dict] = mapped_column(JSON)
    reward_points: Mapped[int] = mapped_column(Integer)
    period: Mapped[ChallengePeriod] = mapped_column(_enum(ChallengePeriod))


class PointsLog(Base):
    """append-only 원장. 잔액은 SUM(amount)로 계산하고 행을 수정·삭제하지 않는다."""

    __tablename__ = "points_log"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int] = mapped_column(Integer)
    ref_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()
