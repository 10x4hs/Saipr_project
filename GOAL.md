# GOAL — 함께읽기 MVP v0.1.0

> 근거: [docs/PRD.md](docs/PRD.md) 11장 마일스톤 · 결정 로그: [.grill/reading-together-mvp.md](.grill/reading-together-mvp.md)

## Objective

두 명 이상의 사용자가 초대 링크 하나로 같은 퍼블릭 도메인 도서의 읽기방에 들어가, 각자 인앱 리더로 읽는 동안
**서로의 검증된 진행률과 문단 반응(스포일러 가드 적용)이 1초 이내(P95)에 보이는 웹 MVP**를 완성한다.
완료 판정은 아래 검증 항목이 **모두** 통과하는 것이다.

## Verification (binary)

| # | 검증 | 기준 |
|---|---|---|
| 1 | `pytest -q` | 전부 통과, 실패 0 |
| 2 | `ruff check .` | 오류 0 |
| 3 | GitHub Actions CI | `main` 최신 커밋 녹색 |
| 4 | `docker compose up` → `alembic upgrade head` | 빈 Postgres에서 오류 없이 적용 |
| 5 | E2E 시나리오 테스트 (Phase 3에서 추가) | 사용자 A 방 생성 → B 초대 링크 입장 → A가 청크 검증 → B의 WebSocket이 1초 내 `progress.updated` 수신 |
| 6 | 체류시간 검증 테스트 | 최소 체류시간 미달 청크는 진행률·레이스 점수에 0 반영 |
| 7 | 스포일러 가드 테스트 | B의 검증 위치보다 뒤 청크 반응은 본문 없이 개수만 반환 |
| 8 | 저작권 가드 테스트 | `gutendex`·`wikisource` 이외 소스는 `has_fulltext=true`·본문 저장 불가 |

## Phase checklist

- [x] **Phase 0** — FastAPI · SQLAlchemy · Alembic · Docker Compose · CI
- [x] **Phase 1** — 도서 소스 어댑터 5종, 통합 검색(부분 실패 허용), 전문 청크화 (31 tests)
- [ ] **Phase 2** — 소셜 로그인(카카오·구글·네이버), 내 서재, 리더 이벤트 API, 트래커 모드
- [ ] **Phase 3** — 읽기방 · 초대 코드 · WebSocket 브로커 · 반응 · 스포일러 가드 (검증 5·7)
- [ ] **Phase 4** — 페이지 레이스(체류시간) · 한줄평 배틀 · 포인트 원장 (검증 6)
- [ ] **Phase 5** — 팀 · 주간 리그 · 리더보드
- [ ] **Phase 6** — FCM 푸시 · 스테이징 배포

## Design decision (Phase 2 착수 전 게이트)

팀 투표로 **시안 A(Glass v2) 또는 B(종이 서재) 중 하나를 확정**하고, 선택안의 토큰을 `docs/design-system.md`에 단일 기준으로 남긴다.

- 근거 자료: README의 테마 선택 표, `docs/mockups/glass-v2.html` · `docs/mockups/paper-b.html` (두 시안 6화면씩)
- 완료 판정: 팀원 과반 득표안 결정 → 탈락안 목업은 `docs/mockups/archive/`로 이동 → 리더 화면 가독성 기준(본문 16px 이상 · 대비 AA) 통과
- 동률이면: 리더 화면 한 장만 두 시안으로 5분 실사용 테스트 후 재투표

## Scope

- In: 웹 MVP 백엔드(FastAPI) + Reflex 웹 프론트, 퍼블릭 도메인 전문, 상용 도서 메타데이터·수동 진행률.
- Out: 퀴즈, 상용 본문, 네이티브 앱, 결제, 알라딘 API (PRD 7장).

## Stop and ask when

- 새 외부 API 키·유료 서비스·약관 동의가 필요할 때
- PRD의 원칙(본문 합법 소스만, 스포일러 가드 기본 ON)과 충돌하는 구현이 필요할 때
- 한 Phase가 예상 대비 2배 이상 커져 범위 조정이 필요할 때
