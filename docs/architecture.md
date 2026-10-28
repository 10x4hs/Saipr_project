# 아키텍처

```
app/
  main.py              FastAPI 앱, lifespan에서 공용 httpx.AsyncClient 생성
  core/config.py       pydantic-settings — 환경변수(.env)
  db/                  DeclarativeBase(제약 이름 규칙) · async 세션
  models.py            전체 스키마 (PRD 10장과 1:1)
  sources/             외부 도서 소스 어댑터 (어댑터 패턴)
    base.py            BookSource(ABC) · BookMeta · SourceError
    kakao/naver/google_books.py   메타데이터 전용
    gutendex/wikisource.py        퍼블릭 도메인 전문 (fetch_book 구현)
    registry.py        키가 있는 소스만 우선순위 순서로 활성화
  services/
    search.py          병렬 조회 · ISBN 병합 · 부분 실패 허용 · 전문 화이트리스트
    chunker.py         본문 → 청크 (페이지 대체 위치 단위)
    pace.py            체류시간 검증 규칙
    books.py           전문 가져오기(캐시) · 청크 조회
  api/books.py         /api/v1/books/*
migrations/            Alembic (async)
```

## 핵심 결정

| 결정 | 이유 |
|---|---|
| **어댑터 패턴** — 소스마다 `search`, 전문 소스만 `fetch_book` | 출판사 제휴 시 파일 하나 추가로 확장 |
| **전문 화이트리스트를 코드로 강제** (`FULLTEXT_SOURCES`) | 저작권 원칙이 실수로 깨지지 않도록. 메타데이터 소스가 `has_fulltext=True`를 줘도 병합 단계에서 꺼짐 |
| **부분 실패 허용** — `asyncio.gather(return_exceptions=True)` + 소스별 `wait_for` | 한 API가 죽어도 검색은 동작 |
| **오류는 타입명만 노출** | httpx 예외 메시지에 API 키가 담긴 URL이 포함될 수 있음 |
| **청크 = 위치 단위** | 판본·기기마다 달라지는 페이지 대신 결정적 분할 결과를 공유 좌표로 사용 |
| **포인트는 append-only 원장** | 감사 추적, 잔액 = SUM |
| **테스트는 네트워크 0** | `httpx.MockTransport`로 외부 API 대체, DB는 in-memory SQLite |

## API

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| GET | `/api/v1/books/search?q=&limit=` | 통합 검색 → `items[]`, `errors{source: ExceptionType}` |
| POST | `/api/v1/books/import` | `{source, external_id}` 퍼블릭 도메인 전문 가져오기 (400: 비허용 소스, 422: 본문 없음, 502: 상위 장애) |
| GET | `/api/v1/books/{id}/chunks/{index}` | 청크 본문 + `min_dwell_ms` |

## 추가된 구성 (2026-10)

```
app/auth.py            이메일 세션 인증 — BCrypt(12), 30분 유휴 만료, 로그인 시 세션 재발급, CSRF
app/web.py             모바일 웹 앱 화면(Jinja2) — 홈 3D, 탐색, 서재, 대결, 리더, 화면 꾸미기
app/api/me.py          화면 꾸미기 저장 (users.settings)
app/api/social.py      반응 · 친구 진행 · 대결 순위 · WebSocket /api/v1/ws/books/{id}
app/realtime.py        책 단위 인메모리 브로커
app/services/races.py  대결방(rooms) — 초대 코드, 정원 8, 순위 = 검증된 청크 수
app/services/social.py 반응 + 스포일러 가드, 같은 방 범위(circle)
app/services/uploads.py EPUB·PDF·TXT → 본문, DRM 거부, 본문 지문(같은 책 판별)
app/core/appearance.py 테마 · 배경 30종 · 강조 색 12종 (looks.css와 짝)
```

| 결정 | 이유 |
|---|---|
| **체류시간은 서버가 잰다** — 쪽을 펼친 시각(reading_events)부터 "다 읽음" 요청까지 | 클라이언트의 verified 값을 믿으면 API 한 번으로 레이스 점수를 올릴 수 있다 |
| **WebSocket 이벤트에 반응 본문을 싣지 않는다** | 받는 쪽이 자기 스포일러 가드가 걸린 API로 다시 읽게 해서, 소켓으로 스포일러가 새지 않게 |
| **반응은 같은 방(circle) 안에서만** | 모르는 사람의 반응이 섞이지 않게(PRD ROOM-03) |
| **화면 꾸미기는 계정에 저장, 서버가 렌더링 때 적용** | 모든 기기 동일, 첫 화면부터 깜빡임 없음 |
| **3D는 CSS transform + 작은 JS** (책 상자, 롤러 홈, StPageFlip) | 빌드 단계 없이 Python 서버만으로 배포 |

| Method | Path | 설명 |
|---|---|---|
| PUT | `/api/v1/books/{id}/progress` | `{chunk_index, verified}` — 펼침 기록 / 서버 체류시간 판정, 같은 방에 `progress.updated` |
| GET·POST | `/api/v1/books/{id}/reactions` | 반응 목록(가드 적용) / 남기기, 같은 방에 `reaction.added` |
| GET | `/api/v1/books/{id}/social` | 같은 방 친구 진행 · 봉인된 반응 수 |
| GET | `/api/v1/races/{id}/standings` | 대결 순위 |
| PUT | `/api/v1/me/settings` | 테마 · 배경 · 강조 색 |
| WS | `/api/v1/ws/books/{id}` | 실시간 이벤트 (로그인 세션 필요, 아니면 4401) |

## 다음 Phase에서 채울 자리

- 소셜 로그인(Authlib)을 `app/auth.py` 옆에 붙인다 (oauth_accounts 테이블은 이미 있음)
- 서버를 여러 대로 늘리면 `app/realtime.py`의 Broker를 Redis Pub/Sub 구현으로 교체
