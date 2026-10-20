# 아키텍처

화면은 **Flet(Python) 네이티브 앱**(`mobile/`)이 그리고, 서버는 **FastAPI 하나**입니다. 앱은 JSON API(`/api/v1`, Bearer 토큰)와 WebSocket(`/ws/*?token=`)만 씁니다.
서버가 그리는 웹 화면은 초대 링크 미리보기(`/r/{코드}`)와 로그인·가입(소셜 로그인 콜백 포함)만 남겼습니다.
(Phase 1까지 있던 Spring Boot 인증 서버는 `app/services/auth.py`로 옮기고 삭제했습니다.)

```
안드로이드 앱(Flet) ──HTTPS JSON(Bearer)──▶ FastAPI ──SQLAlchemy(async)──▶ SQLite(로컬) / Postgres(Docker·배포)
   ▲                                          │
   └──────────WebSocket(?token=)──────────────┘  ◀── 커밋 후 아웃박스 → 인메모리 브로커(방·사용자 채널, 최근 100건 버퍼)
브라우저 ──── /r/{코드} 미리보기 · /login · /signup (세션 쿠키 + CSRF)
```

```
app/
  main.py              앱 조립: 세션 미들웨어 · 라우터 · 예외 → JSON/HTML · lifespan(테이블 생성·챌린지·스케줄러)
  seed.py              시연 데이터 (python -m app.seed)
  data/                퍼블릭 도메인 샘플 도서 16권 (위키문헌 원문 · 소설/시/수필, 위키백과 요약 포함)
  core/
    config.py          환경변수 (.env)
    security.py        scrypt 비밀번호 해시 · 입력 검증 · CSRF 토큰
    clock.py           UTC 저장 · KST 하루/주 경계
  db/
    base.py            제약 이름 규칙
    session.py         엔진 · 세션 · 트랜잭션 아웃박스(defer_publish)
  models.py            전체 스키마 (PRD 10장 + 알림·설정 컬럼)
  realtime/broker.py   publish/subscribe · 재연결 재전송 · 스레드 안전 전달
  sources/             외부 도서 소스 어댑터 (Phase 1)
  services/            비즈니스 규칙 — API와 웹 화면이 같은 함수를 쓴다
    auth.py oauth.py   이메일 가입·로그인 / 카카오·구글·네이버 OAuth (키가 있을 때만)
    library.py         내 서재 · 트래커 모드 · 위치 좌표(position_of)
    reading.py         리더 이벤트 → 체류시간 판정 → 진행률·포인트·브로드캐스트
    rooms.py           읽기방 · 초대 코드 · 방장 위임 · 진행률/추월 알림
    reactions.py       문단 반응 · 스포일러 가드
    battles.py         페이지 레이스 · 한줄평 배틀 · 정산 · 종료 알림(tick)
    teams.py           팀 · 주간 리그
    points.py          포인트 원장 · 챌린지
    notifications.py   알림함 · 방해 금지 · 일 5건 → /ws/me 실시간 (+ 예전 웹 푸시 구독이 있으면 전송)
    push.py            VAPID 키 · 구독 · pywebpush 전송(스레드) · 만료 구독 정리
    scheduler.py       60초마다 battles.tick
  api/                 /api/v1/* JSON API + /ws/* WebSocket
  web/                 남은 웹 화면: 첫 화면 · 로그인 · 가입 · 초대 미리보기 (routes.py · view.py · templates/ · static/css/glass.css)
mobile/                Flet 앱 — 자세한 구조는 mobile/README.md
  src/saipr/app.py     앱 상태 · 화면 스택 · 로그인 · /ws/me 알림 · 알림 링크 → 화면
  src/saipr/core/      api(Bearer 클라이언트) · realtime(재연결 채널) · reading(체류시간·큐·속도) · store · fmt
  src/saipr/ui/        theme.py(Glass · Material 3 · Cupertino × 라이트/다크) · widgets.py
  src/saipr/views/     start · home · explore · book · reader · library · together · room · profile · me
tools/                 make_icons.py(앱 아이콘을 순수 Python으로 그림)
migrations/            Alembic (Postgres용). SQLite는 시작할 때 create_all
```

## 핵심 결정

| 결정 | 이유 |
|---|---|
| **화면은 앱, 규칙은 서버** — 앱은 JSON API만 부르고, 남은 웹 화면도 같은 `services/*` 함수를 쓴다 | 규칙(스포일러 가드, 체류시간)이 서버 한 곳에만 있어 앱을 바꿔도 어긋나지 않는다 |
| **Flet(Python)으로 네이티브 앱** | 웹 화면은 "앱 느낌이 없다"는 피드백. 팀이 아는 Python 하나로 안드로이드 APK까지 만들고, Material·Cupertino 위젯을 그대로 쓴다 |
| **앱은 Bearer 토큰, 웹은 세션 쿠키** | 앱에는 쿠키·CSRF가 어울리지 않는다. 토큰은 해시로만 저장하고 로그아웃 시 폐기 |
| **체류시간은 서버가 다시 계산** — `min(보낸 값, 직전 이벤트와의 간격, 최소×10)` | 클라이언트 값을 그대로 믿으면 "60초 읽었다"고 거짓말할 수 있다 |
| **서버 시계 예산** — 한 배치의 인정 시간 합 ≤ 직전 배치 수신 뒤 실제로 흐른 시간, 지난 동기화보다 앞선 시각은 0 | `occurred_at`도 클라이언트가 정하는 값이라, 쉬었다가 "지난 하루 동안 읽었다"고 꾸밀 수 있다 (코드 리뷰에서 발견) |
| **한 청크는 한 번만 verified** (DB 조건부 UNIQUE) | 레이스 점수 = verified 이벤트 수. 재방문·동시 탭으로 점수가 부풀지 않는다 |
| **정산은 조건부 UPDATE로 선점**, 포인트는 `(user, source, ref_id)` 조건부 UNIQUE | 스케줄러와 화면 열기가 동시에 정산해도 한 번만 지급 |
| **배틀 중에는 팀원 고정**, 두 팀 모두 2명 이상·겹치는 사람 없음 | 끝나기 직전 이긴 팀에 들어가 상금을 받거나, 나가서 결과를 바꾸는 것을 막는다 |
| **완독 포인트는 앱에서 끝까지 검증된 책만** | 트래커 진행률은 본인 입력이라, 가짜 책으로 포인트를 무한히 받을 수 있다 |
| **트랜잭션 아웃박스** — 이벤트는 커밋이 성공한 뒤에만 보낸다 | DB에 없는 진행률이 화면에 뜨는 일이 없다. 롤백되면 버린다 |
| **반응 이벤트에 본문을 싣지 않음** | 받는 사람마다 스포일러 가드가 다르다. 알림만 받고 API로 다시 조회한다 |
| **인메모리 브로커** (Redis 대신) | 단일 인스턴스 MVP. 같은 인터페이스로 Redis Pub/Sub 구현을 끼울 수 있다 |
| **리셋 없는 기간 집계** — 챌린지·리그는 기간 시작 시각으로 계산, 지급은 `ref_id`(기간 키)로 중복 방지 | 스케줄러가 멈춰도 결과가 틀리지 않는다 |
| **포인트는 append-only 원장** | 감사 추적, 잔액 = SUM |
| **웹 푸시도 커밋 후에만** (`defer_task`) | 롤백된 알림이 폰에 뜨지 않게. 전송은 백그라운드 스레드라 요청을 늦추지 않는다 |
| **웹은 세션 쿠키 + CSRF 토큰** | HttpOnly·SameSite=Lax 쿠키, 상태를 바꾸는 요청은 헤더/폼 토큰 확인, 로그인 시 세션 교체 |
| **소셜 계정을 같은 이메일 계정에 자동 연결하지 않음** | 제공자가 이메일 소유를 확인하지 않았으면 계정 탈취가 가능하다 |
| **테스트는 네트워크 0** | 외부 API는 `httpx.MockTransport`, DB는 SQLite. 실시간 E2E는 CI에서 Postgres로도 돈다 |

## API

앱은 `Authorization: Bearer <토큰>`으로 부르고(CSRF 생략), 세션 쿠키로 부를 때는 상태를 바꾸는 요청(POST/PUT/DELETE)에 `X-CSRF-Token` 헤더가 필요합니다. 전체 명세는 서버 실행 후 `/docs`.

| 영역 | Method · Path |
|---|---|
| 인증 | `GET /api/v1/auth/csrf` · `POST /signup` · `POST /login` · `POST /logout` · `GET /me` · `PUT /me/settings` |
| 도서 | `GET /api/v1/books/search` · `POST /books/import` · `POST /books/track` · `GET /books/{id}` · `GET /books/{id}/chunks/{i}` |
| 서재 · 리더 | `GET /api/v1/library` · `PUT /library/{book}` · `PUT /library/{book}/progress` · `POST /books/{id}/events` |
| 읽기방 | `POST /api/v1/rooms` · `GET /rooms` · `GET /rooms/{id}` · `GET /invites/{code}` · `POST /invites/{code}/join` · `POST /rooms/{id}/invite` · `POST /rooms/{id}/leave` · `GET /rooms/{id}/race` |
| 반응 | `POST /api/v1/books/{id}/reactions` · `GET /books/{id}/reactions?room_id=` |
| 팀 · 리그 | `POST /api/v1/teams` · `GET /teams` · `POST /teams/join/{code}` · `POST /teams/{id}/leave` · `GET /leagues/{team}` |
| 배틀 (두 팀 팀원만) | `POST /api/v1/battles` · `GET /battles` · `GET /battles/{id}` · `GET·POST /battles/{id}/highlights` · `POST /battles/{id}/highlights/{h}/vote` |
| 포인트 · 알림 | `GET /api/v1/points` · `GET /notifications` · `POST /notifications/read` |
| 웹 푸시 (예전 웹 앱용, 남겨 둠) | `GET /api/v1/push/key` · `POST /push/subscribe` · `POST /push/unsubscribe` · `POST /push/test` |
| 웹 화면 | `GET /` · `GET·POST /login` · `GET·POST /signup` · `POST /logout` · `GET /auth/{provider}/login·callback` · `GET /r/{code}` |
| 실시간 | `WS /ws/rooms/{id}?last_event_id=` (`progress.updated` `reaction.created` `member.joined` `presence.changed` `message.created`) · `WS /ws/me` (`notification.created`) — 앱은 `?token=` |
| 앱 토큰 · 프로필 | `POST /api/v1/auth/token` · `POST /auth/token/signup` · `DELETE /auth/token` · `PUT /auth/me/profile` (Bearer 요청은 CSRF 생략) |
| 책 목록 · 소개 | `GET /api/v1/books?genre=&sort=popular\|new` · `GET /books/{id}/info` (위키백과 요약 DB 캐시) |
| 친구 · 피드 | `GET /api/v1/users/search?q=` · `GET /users/{id}` · `POST·DELETE /users/{id}/follow` · `POST /users/{id}/cheer` · `GET /me/following` · `GET /me/followers` · `GET /feed?before=` |
| 채팅 · 통계 · 밑줄 | `GET·POST /api/v1/rooms/{id}/messages` · `GET /me/stats` · `GET /me/badges` · `POST·GET /books/{id}/highlights` · `GET /me/highlights` · `PATCH·DELETE /highlights/{id}` |

## 규칙 요약 (숫자)

| 규칙 | 값 | 위치 |
|---|---|---|
| 최소 체류시간 | 한글 1,500자/분 · 영문 600단어/분 | `services/pace.py` |
| 인정 상한 | 최소 체류시간 × 10 | `services/pace.py` |
| 늦은 이벤트 | 발생 10분 뒤에 도착하면 레이스 제외(진행률엔 반영). PRD EXC-05의 24시간에서 줄임 | `services/reading.py` |
| 배치 예산 | 직전 수신 뒤 흐른 서버 시간 + 30초 | `services/reading.py` |
| "천천히 읽어도 괜찮아요" | 1분 안에 미검증 청크 5개 연속 | `services/reading.py` |
| 방 | 최대 8명 · 초대 7일 · 8자리 코드 | `services/rooms.py` |
| 팀 | 최대 6명 · 배틀은 2명 이상 · 배틀 중 팀원 고정 · 리그 10팀 | `services/teams.py` |
| 포인트 | 청크 1P(일 100P) · 완독 50P(앱에서 끝까지 읽은 책만) · 배틀 승리 100P | `services/points.py` |
| 투표 | 배틀당 1인 3표 · 자기 글 금지 · 중복 금지 | `services/battles.py` |
| 알림 | 22~08시 보류 · 일 5건 | `services/notifications.py` |
