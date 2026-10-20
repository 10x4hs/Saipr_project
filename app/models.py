"""DB 스키마 — docs/PRD.md 10장 데이터 모델과 1:1 대응."""

import enum
import secrets
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import (
    false as sa_false,
)
from sqlalchemy import (
    true as sa_true,
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


# 친구 코드: 헷갈리는 글자(0·O·1·I)를 뺀 32자 × 6자리 ≈ 10억 가지
FRIEND_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
FRIEND_CODE_LEN = 6
# 웹 화면(app/web/view.py AVATAR_COLORS)과 같은 팔레트
AVATAR_COLORS = ("#3b82f6", "#22a06b", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6", "#ec4899", "#64748b")


def new_friend_code() -> str:
    return "".join(secrets.choice(FRIEND_CODE_ALPHABET) for _ in range(FRIEND_CODE_LEN))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    # 소셜 로그인만 쓰는 사용자는 NULL
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # 스포일러 가드는 방 설정이 아닌 개인 설정 (PRD EXC-03)
    spoiler_guard: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    # 친구 찾기용 공개 코드. 닉네임은 겹칠 수 있어 정확히 한 사람을 찾을 때 쓴다
    friend_code: Mapped[str] = mapped_column(String(FRIEND_CODE_LEN), unique=True, default=new_friend_code)
    bio: Mapped[str | None] = mapped_column(String(160))
    # NULL이면 id로 팔레트에서 고른다(웹 화면과 같은 색) — avatar_color_of()
    avatar_color: Mapped[str | None] = mapped_column(String(9))
    daily_goal_minutes: Mapped[int] = mapped_column(SmallInteger, default=20, server_default=text("20"))
    yearly_goal_books: Mapped[int] = mapped_column(SmallInteger, default=12, server_default=text("12"))
    created_at: Mapped[datetime] = _now()

    @property
    def color(self) -> str:
        return self.avatar_color or AVATAR_COLORS[(self.id or 0) % len(AVATAR_COLORS)]


class ApiToken(Base):
    """네이티브 앱용 Bearer 토큰. 원문은 발급할 때 한 번만 돌려주고 DB에는 SHA-256 해시만 둔다."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Follow(Base):
    """한쪽 방향 팔로우. 친구 공개(friends) 밑줄은 나를 팔로우한 사람에게 보인다."""

    __tablename__ = "follows"
    __table_args__ = (
        CheckConstraint("follower_id <> followee_id", name="not_self"),
        Index("ix_follows_followee", "followee_id"),
    )

    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    followee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = _now()


class Cheer(Base):
    """응원 기록. 복합 PK로 '하루(KST) 같은 사람에게 한 번'을 DB가 강제한다."""

    __tablename__ = "cheers"

    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
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
    # 소설 · 시 · 수필 (번들 도서에만 있고, 가져온 책은 NULL)
    genre: Mapped[str | None] = mapped_column(String(10))
    # 위키백과 요약 캐시 (services/book_info.py). info_fetched_at이 NULL이면 아직 안 받아 봤다
    description: Mapped[str | None] = mapped_column(Text)
    author_bio: Mapped[str | None] = mapped_column(Text)
    wiki_url: Mapped[str | None] = mapped_column(String(1000))
    info_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReadingEvent(Base):
    __tablename__ = "reading_events"
    __table_args__ = (
        Index("ix_reading_events_user_book", "user_id", "book_id", "chunk_index"),
        # 한 청크는 사람마다 한 번만 verified.
        # 동시에 온 두 배치가 레이스 점수를 두 번 올리지 못하게 DB가 막는다
        Index(
            "uq_reading_events_verified_once",
            "user_id",
            "book_id",
            "chunk_index",
            unique=True,
            postgresql_where=text("verified"),
            sqlite_where=text("verified"),
        ),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    dwell_ms: Mapped[int] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # 오프라인 큐로 24시간 넘게 늦게 도착한 이벤트는 레이스 점수에서 뺀다 (PRD EXC-05)
    race_eligible: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 서버가 받은 시각. 클라이언트 시각(occurred_at)과 달리 조작할 수 없어 체류시간 상한의 기준이 된다
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(80))
    mode: Mapped[RoomMode] = mapped_column(_enum(RoomMode), default=RoomMode.ASYNC)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 방장이 나가고 남은 멤버가 없으면 보관 처리 (PRD EXC-06)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
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
    invite_code: Mapped[str | None] = mapped_column(String(16), unique=True)


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = _now()


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
    __table_args__ = (
        Index("ix_highlights_user_book", "user_id", "book_id"),
        Index("ix_highlights_book_chunk", "book_id", "chunk_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    battle_id: Mapped[int | None] = mapped_column(ForeignKey("battles.id", ondelete="SET NULL"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[int] = mapped_column(SmallInteger, default=0)
    quote: Mapped[str] = mapped_column(Text)
    # 개인 밑줄에서는 '메모'(API의 note)로 쓴다
    comment: Mapped[str | None] = mapped_column(String(280))
    color: Mapped[str] = mapped_column(String(10), default="yellow", server_default="yellow")
    # private: 나만 · friends: 나를 팔로우한 사람 (배틀 밑줄은 private로 두고 배틀 화면에서만 보인다)
    visibility: Mapped[str] = mapped_column(String(10), default="private", server_default="private")
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
    __table_args__ = (
        # 같은 사유(완독·배틀 승리·챌린지 기간)로 두 번 적립되지 않도록 DB가 마지막으로 막는다
        Index(
            "uq_points_log_ref",
            "user_id",
            "source",
            "ref_id",
            unique=True,
            postgresql_where=text("ref_id IS NOT NULL"),
            sqlite_where=text("ref_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int] = mapped_column(Integer)
    ref_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


class Notification(Base):
    """앱 내 알림함 (PRD NOTI-01). FCM 대신 WebSocket으로 실시간 전달하고 여기 남긴다."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    body: Mapped[str] = mapped_column(String(280))
    link: Mapped[str | None] = mapped_column(String(300))
    # 방해 금지 시간(22~08시 KST)에 생긴 알림은 이 시각 이후에 보인다
    deliver_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class PushSubscription(Base):
    """브라우저 웹 푸시 구독 (PRD NOTI-01). VAPID로 보내므로 Firebase 계정 없이 동작한다."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = _now()


class Activity(Base):
    """친구 피드 (started · milestone · finished · highlight · joined_room · badge).

    ref는 같은 일이 두 번 기록되지 않게 하는 키다(예: 'started:3', 'milestone:3:50', 'badge:streak_7').
    """

    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_user_id_id", "user_id", "id"),
        Index(
            "uq_activities_user_ref",
            "user_id",
            "ref",
            unique=True,
            postgresql_where=text("ref IS NOT NULL"),
            sqlite_where=text("ref IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    ref: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


class RoomMessage(Base):
    """읽기방 채팅. 스포일러 가드 대상이 아니다(위치와 무관한 대화)."""

    __tablename__ = "room_messages"
    __table_args__ = (Index("ix_room_messages_room_id_id", "room_id", "id"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = _now()
