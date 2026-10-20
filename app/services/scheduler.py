"""주기 작업. APScheduler 대신 asyncio 루프 하나로 충분하다(단일 인스턴스 MVP).

일간·주간 '리셋'은 따로 돌지 않는다. 챌린지와 리그는 기간 시작 시각으로 계산하기 때문이다.
여기서는 배틀 상태 갱신·종료 알림·정산만 한다.
"""

import asyncio
import logging

from app.db.session import SessionLocal
from app.services import battles

log = logging.getLogger(__name__)


async def run_forever(interval_seconds: int) -> None:
    while True:
        try:
            async with SessionLocal() as session:
                result = await battles.tick(session)
            if any(result.values()):
                log.info("scheduler tick: %s", result)
        except Exception:  # 한 번 실패해도 루프는 계속 돈다
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval_seconds)
