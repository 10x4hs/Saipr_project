# GOAL — 함께읽기 v1.0 (안드로이드 앱)

> 근거: [docs/PRD.md](docs/PRD.md) 11장 마일스톤 · 결정 로그: [.grill/reading-together-mvp.md](.grill/reading-together-mvp.md) · [.grill/phase2-6-python-build.md](.grill/phase2-6-python-build.md) · [.grill/native-app-flet.md](.grill/native-app-flet.md)

## Objective

두 명 이상의 사용자가 초대 링크 하나로 같은 퍼블릭 도메인 도서의 읽기방에 들어가, 각자 인앱 리더로 읽는 동안
**서로의 검증된 진행률과 문단 반응(스포일러 가드 적용)이 1초 이내(P95)에 보이는 앱**을 완성한다.
2026-10-20부터 화면은 Flet(Python) 네이티브 앱(`mobile/`)이고, 친구·피드·응원·채팅·통계·밑줄까지 "내일 출시할 수 있는 품질"을 기준으로 한다.
완료 판정은 아래 검증 항목이 **모두** 통과하는 것이다.

## Verification (binary)

| # | 검증 | 기준 |
|---|---|---|
| 1 | `pytest -q` | 전부 통과, 실패 0 |
| 2 | `ruff check .` | 오류 0 |
| 3 | GitHub Actions CI | `main` 최신 커밋 녹색 |
| 4 | `docker compose up` → `alembic upgrade head` | 빈 Postgres에서 오류 없이 적용 |
| 5 | E2E 시나리오 테스트 (`tests/test_realtime.py`) | 사용자 A 방 생성 → B 초대 링크 입장 → A가 청크 검증 → B의 WebSocket이 1초 내 `progress.updated` 수신 |
| 6 | 체류시간 검증 테스트 (`tests/test_reading.py`) | 최소 체류시간 미달 청크는 진행률·레이스 점수에 0 반영 |
| 7 | 스포일러 가드 테스트 (`tests/test_rooms.py`) | B의 검증 위치보다 뒤 청크 반응은 본문 없이 개수만 반환 |
| 8 | 저작권 가드 테스트 (`tests/test_rooms.py::test_copyright_guard`) | `gutendex`·`wikisource` 이외 소스는 `has_fulltext=true`·본문 저장 불가 |
| 9 | `cd mobile && pytest -q` · `ruff check .` | 앱 로직·세 디자인 × 라이트/다크 위젯 테스트 통과 |
| 10 | 앱 화면 점검 (Flet 웹 모드 + Playwright Pixel 7) | 모든 탭·상세 화면이 세 디자인에서 깨짐 없이 그려지고, 반응·채팅·디자인 전환·실시간 수신이 동작 |
| 11 | `flet build apk` | APK 생성 — JDK 17이 필요해 사용자 환경에서 실행 |

## Phase checklist

- [x] **Phase 0** — FastAPI · SQLAlchemy · Alembic · Docker Compose · CI
- [x] **Phase 1** — 도서 소스 어댑터 5종, 통합 검색(부분 실패 허용), 전문 청크화 (31 tests)
- [x] **Phase 2** — 이메일 가입·로그인(Spring Boot → FastAPI 이전) + 소셜 로그인(카카오·구글·네이버, 키가 있을 때만), 내 서재, 리더 이벤트 API, 트래커 모드
- [x] **Phase 3** — 읽기방 · 초대 코드 · WebSocket 브로커 · 반응 · 스포일러 가드 (검증 5·7)
- [x] **Phase 4** — 페이지 레이스(체류시간) · 한줄평 배틀 · 포인트 원장 · 챌린지 (검증 6)
- [x] **Phase 5** — 팀 · 주간 리그 · 리더보드
- [x] **Phase 6** — 앱 내 알림함(WebSocket 실시간, 방해 금지·일 5건) + VAPID 웹 푸시(FCM 계정 없이) · PWA 설치·오프라인 · 배포 설정(`Dockerfile`, `render.yaml`). 실제 배포는 계정이 필요해 제외 (PWA·웹 화면은 Phase 7에서 앱으로 대체)
- [x] **Phase 7** — Flet 네이티브 앱(5탭 · 리더 · 읽기방 채팅 · 친구 · 통계 · 밑줄 · 디자인 3종) + 앱 토큰·친구·피드·채팅·통계·밑줄 API, 웹은 초대 미리보기·로그인만

### 2026-10-20 검증 결과 (로컬)

| # | 결과 |
|---|---|
| 1 | `pytest -q` 110개 통과 · `tools/browser_check.py` Chromium(Pixel 7)·WebKit(iPhone 15) PASS |
| 2 | `ruff check .` 오류 0 |
| 3 | PR CI에서 확인 |
| 4 | Docker가 없는 환경이라 임베디드 Postgres 16(`pgserver`)으로 `upgrade → downgrade → upgrade` + `alembic check` 통과 |
| 5 | SQLite·Postgres 둘 다 통과, 수신까지 1초 미만 |
| 6·7·8 | 통과 |

코드 리뷰에서 나온 점수·포인트 우회 경로 6건(체류시간 시각 조작, 트래커 완독 포인트 반복, 중복 정산, 중복 검증, 배틀 중 팀 이동, 시간대 밀림)은
고치고 `tests/test_integrity.py`에 회귀 테스트로 남겼다. 그 과정에서 PRD와 달라진 규칙:
레이스 인정은 '발생 후 10분 안에 도착한 이벤트'(PRD EXC-05는 24시간), 완독 포인트는 앱에서 끝까지 읽은 책만, 배틀 중 팀원 고정.

### 2026-10-20 검증 결과 — 네이티브 앱

| # | 결과 |
|---|---|
| 1 | 서버 `pytest -q` 147개 통과 |
| 2 | `ruff check .` 오류 0 (mobile 포함) |
| 9 | 앱 `pytest -q` 20개 통과 |
| 10 | 11개 화면 × Glass 라이트 확인, 홈·나·리더는 Material·Cupertino·다크까지. 좌표 탭으로 문단 반응 보내기, 채팅 보내기, 설정에서 디자인 바로 바꾸기, 다른 계정이 보낸 채팅 실시간 수신 확인. 서버가 꺼져 있으면 첫 화면에 "연결 안 됨" |
| 11 | 미실행 — JDK 17 미설치(사용자가 직접 설치 예정). 명령은 [mobile/README.md](mobile/README.md) |

## Design decision (결정됨)

처음 시안 **A(Glass v2)**를 앱 전체에 그대로 재현했다(리더는 유리 틀 + 종이색 본문, 레이스는 밤 배경). 기준은 [docs/design-system.md](docs/design-system.md), 결정 과정은 [.grill/ui-rebuild-glass.md](.grill/ui-rebuild-glass.md).
중간에 시도한 Index(색인) 방향은 "웹페이지 같고 삭막하다"는 피드백으로 폐기했다.
리더 가독성 기준(본문 16px 이상 · 대비 AA)은 종이 시트 위 잉크색 #2a251f(대비 AAA) · 기본 16.5px(4단계 조절)로 통과.

## Scope

- In: 웹 MVP 백엔드(FastAPI) + Jinja2 서버 렌더링 웹 화면(Reflex 대신 — 설치가 가볍고 WebSocket 연동이 단순), 퍼블릭 도메인 전문, 상용 도서 메타데이터·수동 진행률.
- In(2026-10-20 추가): Flet 안드로이드 앱. 웹 화면은 초대 미리보기·로그인·가입만.
- Out: 퀴즈, 상용 본문, 스토어 출시·앱 푸시(FCM), 결제, 알라딘 API (PRD 7장), Redis(인메모리로 대체).

## Stop and ask when

- 새 외부 API 키·유료 서비스·약관 동의가 필요할 때
- PRD의 원칙(본문 합법 소스만, 스포일러 가드 기본 ON)과 충돌하는 구현이 필요할 때
- 한 Phase가 예상 대비 2배 이상 커져 범위 조정이 필요할 때
