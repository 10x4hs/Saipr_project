"""시연용 데이터. `python -m app.seed` (이미 있는 데이터는 건드리지 않음, 여러 번 실행해도 안전).

- 퍼블릭 도메인 샘플 도서 3권(app/data/sample_books.json, 위키문헌 원문). 인터넷이 없어도 시연할 수 있다.
- 데모 계정 4명 (비밀번호 모두 demo1234), 읽기방 1개, 팀 2개, 진행 중 페이지 레이스 1개.
"""

import asyncio
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app import models  # noqa: F401
from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Battle, BattleType, Book, BookChunk, Room, Team, User
from app.services import battles, rooms, teams
from app.services.chunker import chunk_text, target_for
from app.services.points import ensure_challenges

SAMPLES = Path(__file__).parent / "data" / "sample_books.json"
PASSWORD = "demo1234"
DEMO_USERS = [
    ("서연", "seoyeon@demo.kr"),
    ("준호", "junho@demo.kr"),
    ("도윤", "doyoon@demo.kr"),
    ("민지", "minji@demo.kr"),
]


async def load_samples(session) -> list[Book]:
    books = []
    for item in json.loads(SAMPLES.read_text(encoding="utf-8")):
        book = await session.scalar(
            select(Book).where(Book.source == item["source"], Book.external_id == item["external_id"])
        )
        if book is None:
            chunks = chunk_text(item["text"], target_for(item["language"]))
            book = Book(
                source=item["source"],
                external_id=item["external_id"],
                title=item["title"],
                author=item["author"],
                language=item["language"],
                has_fulltext=True,
                total_chunks=len(chunks),
                chunks=[BookChunk(chunk_index=i, text=c, char_count=len(c)) for i, c in enumerate(chunks)],
            )
            session.add(book)
            await session.commit()
        books.append(book)
    return books


async def main() -> None:
    if get_settings().database_url.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await ensure_challenges(session)
        books = await load_samples(session)

        users = []
        hashed = hash_password(PASSWORD)
        for nick, email in DEMO_USERS:
            u = await session.scalar(select(User).where(User.email == email))
            if u is None:
                u = User(nickname=nick, email=email, password_hash=hashed)
                session.add(u)
                await session.commit()
            users.append(u)
        seoyeon, junho, doyoon, minji = users

        room = await session.scalar(select(Room).where(Room.name == "봄봄 같이 읽기"))
        if room is None:
            room = await rooms.create_room(session, seoyeon, books[0], "봄봄 같이 읽기")
            await rooms.join(session, room.invite_code, junho)

        team_a = await session.scalar(select(Team).where(Team.name == "봄봄단"))
        if team_a is None:
            team_a = await teams.create_team(session, seoyeon, "봄봄단")
            await teams.join_team(session, team_a.invite_code, junho)
        team_b = await session.scalar(select(Team).where(Team.name == "동백꽃파"))
        if team_b is None:
            team_b = await teams.create_team(session, doyoon, "동백꽃파")
            await teams.join_team(session, team_b.invite_code, minji)

        if await session.scalar(select(Battle.id)) is None:
            now = utcnow()
            await battles.create_battle(
                session, seoyeon, BattleType.PAGE_RACE, books[0], team_a, team_b, now, now + timedelta(days=7)
            )

        print("시드 완료")
        print(f"  도서 {len(books)}권: " + ", ".join(b.title for b in books))
        print(f"  데모 계정 (비밀번호 {PASSWORD}): " + ", ".join(e for _, e in DEMO_USERS))
        print(f"  초대 링크: {get_settings().public_base_url}/r/{room.invite_code}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
