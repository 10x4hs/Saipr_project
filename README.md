<div align="center">

# 제목: 미정

**쉬운 독서를 위해**

같은 책을 각자의 속도로 읽으면서 친구의 진행률과 문단 반응이 실시간으로 겹쳐 보이고,
팀을 짜서 공정한 페이지 레이스로 경쟁합니다.

 **[PRD](docs/PRD.md)** · [디자인 시스템](docs/design-system.md) · [아키텍처](docs/architecture.md) · [GOAL](GOAL.md) · [Figma](https://www.figma.com/design/mp2nKNmBdJ7Dg2rc2p9rht)

<img src="docs/images/index-01-home.png" width="260" alt="홈"> <img src="docs/images/index-03-reader.png" width="260" alt="리더"> <img src="docs/images/index-04-room.png" width="260" alt="읽기방">

</div>

---

## 왜 만드나

| 기존 | 한계 | 함께읽기 |
|---|---|---|
| 밀리의서재 | 개인 챌린지뿐, 유저 간 대결 없음 | 친구·팀 대항 페이지 레이스 |
| 실시간 함께읽기 서비스 | 같은 시간에 접속해야 함 | **비동기 기본** — 먼저 읽은 친구의 반응이 문단 옆에 남음 |
| 독서 기록 SNS | 다 읽은 뒤 피드 공유에 그침 | **읽는 도중**의 동행 |
| 공통 | 콘텐츠 라이선싱이 진입장벽 | 본문은 퍼블릭 도메인만, 나머지는 메타데이터 + 진행률 |

타깃: 독서모임은 부담스럽고 혼자 읽기는 지속이 안 되는 대학생·2030. 자세한 페르소나·사용자 스토리·기능 명세·성공 지표는 **[PRD](docs/PRD.md)**.

## 핵심 개념

- **하이브리드 콘텐츠** — 저작권 만료작(위키문헌·Gutendex)은 앱 안 리더로 전문을 읽고, 시판 도서는 카카오·네이버·Google Books 메타데이터와 수동 진행률(트래커 모드)로 기록합니다. 본문 제공 소스는 코드에서 화이트리스트로 강제합니다.
- **청크 = 공통 위치** — 판본·기기마다 달라지는 "페이지" 대신 본문을 결정적으로 나눈 청크를 좌표로 씁니다. 그래서 반응이 모든 사람에게 같은 문단에 겹칩니다.
- **스포일러 가드** — 내가 아직 안 읽은 위치의 반응은 내용 없이 "🔒 앞에서 N개의 반응이 기다리고 있어요"로만 보입니다.
- **체류시간 검증** — 청크 글자 수 대비 최소 체류시간을 **서버가** 다시 계산해, 넘기기만 한 구간은 진행률·레이스 점수에서 빠집니다.

## 빠른 시작

Python 3.12만 있으면 됩니다. Docker·외부 API 키 없이 바로 시연할 수 있어요.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m app.seed                                   # 샘플 도서 3권 + 데모 계정 4개 + 방·팀·레이스
uvicorn app.main:app --reload
```

브라우저에서 <http://localhost:8000> 을 열고 데모 계정으로 로그인합니다. 비밀번호는 모두 `demo1234`.

| 계정 | 역할 |
|---|---|
| `seoyeon@demo.kr` (서연) | 「봄봄 같이 읽기」 방장, 팀 봄봄단 |
| `junho@demo.kr` (준호) | 방 멤버, 팀 봄봄단 |
| `doyoon@demo.kr` (도윤) | 팀 동백꽃파 |
| `minji@demo.kr` (민지) | 팀 동백꽃파 |

샘플 도서는 위키문헌 원문 김유정 「봄봄」·「동백꽃」, 현진건 「운수 좋은 날」입니다. 세 작가 모두 사망 후 70년이 지나 퍼블릭 도메인이고, 인터넷이 없어도 읽을 수 있게 [app/data/](app/data/)에 넣어 두었어요.

Postgres로 돌리려면 `cp .env.example .env && docker compose up --build`를 실행하세요. 마이그레이션과 시드가 자동으로 적용됩니다.

## 시연 순서 (5분)

브라우저 창 두 개를 띄웁니다. 하나는 일반 창, 하나는 시크릿 창이에요.

1. **창 A — 서연 로그인** → 홈. 상단 라임 띠에 친구 진행률이 흐르고, `지금 읽는 중`·`내 읽기방`·`이번 주 레이스`가 보여요.
2. **창 A — 「봄봄 같이 읽기」 방 열기** → 아래쪽 `[03] 초대 링크`를 복사합니다.
3. **창 B — 초대 링크 붙여넣기** → 로그인 전에도 방 미리보기(책·멤버·진행률)가 보여요 → `처음이면 가입하기` → 가입하면 같은 초대 화면으로 돌아와요 → `참여하기`.
4. **창 A의 방 화면** — 새 멤버가 눈금자에 나타나고 활동 로그에 `○○님이 들어왔어요`가 새로고침 없이 찍혀요.
5. **창 B — `함께 읽기 →`(리더)** → 한 청크를 1분 정도 읽고 다음 청크로 스크롤합니다(10초마다 서버로 전송). 청크 머리가 `✓ 검증됨`으로 바뀌고 `+1P` 토스트가 떠요.
   - 빨리 넘기기만 하면 검증되지 않고 "천천히 읽어도 괜찮아요"가 떠요.
6. **창 A의 방 화면** — B의 마커가 오른쪽으로 움직이고, 방 안 레이스 순위가 바뀌어요.
7. **창 B — 문단 탭** → 이모지·한줄평 남기기. **창 A의 리더**에서는 아직 그 위치를 안 읽었으니 `🔒 앞에서 1개의 반응이 기다리고 있어요`로만 보여요(스포일러 가드). `내 정보 → 스포일러 가드 끄기`를 누르면 보여요.
8. **팀·리그 → 봄봄단 → 배틀 신청**으로 레이스·한줄평 배틀, **내 정보**에서 포인트·챌린지·52주 아카이브·알림함을 보여 줍니다.

## 화면

디자인은 refs.gallery Experimental 카테고리를 조사해 정한 **Index(색인)** 방향입니다. 흑백 헤어라인 위에 라임·핑크를 채움으로만 쓰고, 리더 본문은 장식 없이 Noto Serif KR 18px로 둡니다. 근거와 토큰은 [디자인 시스템](docs/design-system.md)에 있어요.

| 홈 | 검색 | 리더 |
|---|---|---|
| <img src="docs/images/index-01-home.png" width="260"> | <img src="docs/images/index-02-search.png" width="260"> | <img src="docs/images/index-03-reader.png" width="260"> |
| **읽기방** | **레이스** | **팀·리그** |
| <img src="docs/images/index-04-room.png" width="260"> | <img src="docs/images/index-05-race.png" width="260"> | <img src="docs/images/index-06-league.png" width="260"> |

이전 시안 A(Glass)·B(Paper)는 [docs/mockups/archive/](docs/mockups/archive/)에 보관했어요.

## 기능

| Phase | 기능 | 화면 · API |
|---|---|---|
| 1 | 통합 도서 검색(5개 소스 병렬, 부분 실패 허용) · 퍼블릭 도메인 전문 가져오기 · 청크화 | `/search` |
| 2 | 이메일 가입·로그인 · 소셜 로그인(카카오·구글·네이버, 키 있을 때만) · 내 서재(읽고 싶은/읽는 중/완독) · 인앱 리더(글자 4단계·배경 3종) · 트래커 모드(% 또는 쪽수) | `/login` `/books/{id}` `/books/{id}/read` |
| 3 | 읽기방(최대 8명, 비동기/동시 모드) · 8자리 초대 링크(7일, 재발급) · WebSocket 실시간 진행률·프레즌스 · 문단 반응 · 스포일러 가드 · 방장 위임 | `/rooms/{id}` `/r/{code}` |
| 4 | 체류시간 검증 페이지 레이스 · 한줄평 배틀(1인 3표) · 포인트 원장 · 챌린지 4종. 배틀 중에는 팀원이 고정되고, 완독 포인트는 앱에서 끝까지 읽은 책만 | `/battles/{id}` `/me` |
| 5 | 팀(최대 6명, 초대 코드) · 주간 리그(월 00:00 KST 기준, 10팀씩) | `/teams` |
| 6 | 앱 내 알림함(추월·반응·배틀·입장) · 방해 금지 22~08시 · 하루 5건 · 배포 설정 | `/me` · `render.yaml` |

JSON API 전체는 서버 실행 후 <http://localhost:8000/docs> 에서 볼 수 있어요. 구조와 설계 결정은 [아키텍처](docs/architecture.md).

## 테스트

```bash
pytest -q        # 100개 — 외부 네트워크 없이 실행 (httpx.MockTransport + SQLite)
ruff check .
```

GOAL의 검증 항목과 테스트의 대응:

| GOAL | 테스트 |
|---|---|
| 5 · A 방 생성 → B 초대 입장 → A 청크 검증 → B WebSocket 1초 내 수신 | `tests/test_realtime.py::test_e2e_progress_reaches_friend_within_one_second` |
| 6 · 최소 체류시간 미달 청크는 진행률·점수 0 | `tests/test_reading.py` |
| 7 · 검증 위치 뒤 반응은 개수만 | `tests/test_rooms.py::test_spoiler_guard_hides_reactions_ahead` |
| 8 · 화이트리스트 밖 소스는 전문 불가 | `tests/test_rooms.py::test_copyright_guard` |
| 점수·포인트 우회 경로 (코드 리뷰) | `tests/test_integrity.py` |

CI(GitHub Actions)는 SQLite 테스트와 함께, 실제 Postgres에서 마이그레이션 왕복 · `alembic check` · 시드 · 실시간 E2E를 돌립니다.

## 환경 변수

모두 선택이에요. 없으면 SQLite + 키 없는 소스(위키문헌·Gutendex·Google Books)로 동작합니다. 전체 목록은 [.env.example](.env.example).

| 변수 | 설명 |
|---|---|
| `DATABASE_URL` | 기본 `sqlite+aiosqlite:///./saipr.db`. Postgres는 `postgresql+asyncpg://…` (`postgres://`도 자동 변환) |
| `SECRET_KEY` | 세션 쿠키 서명 키. **배포 시 반드시 변경** |
| `SESSION_COOKIE_SECURE` | HTTPS 배포 시 `true` |
| `PUBLIC_BASE_URL` | 초대 링크·OAuth 콜백 주소 |
| `KAKAO_REST_API_KEY` · `NAVER_CLIENT_ID/SECRET` · `GOOGLE_BOOKS_API_KEY` | 도서 검색 소스 |
| `KAKAO_LOGIN_ENABLED` · `GOOGLE_CLIENT_ID/SECRET` · `NAVER_LOGIN_ENABLED` | 소셜 로그인 버튼 켜기. 콜백: `{PUBLIC_BASE_URL}/auth/{provider}/callback` |
| `SEED_DEMO` | Docker 시작 시 데모 데이터 넣기 (Dockerfile 기본 `true`, `render.yaml`은 `false` — 공개 시연용이면 켜기) |

## 배포

계정 연결이 필요해 실제 배포는 하지 않았고, 설정 파일만 준비했어요.

- **Render**: 저장소를 연결하고 *Blueprint*로 [render.yaml](render.yaml)을 선택하면 웹 서비스 + Postgres가 만들어지고 `SECRET_KEY`는 자동 생성돼요. 배포 후 `PUBLIC_BASE_URL`을 `https://<서비스>.onrender.com`으로 설정하세요.
- **그 밖의 Docker 호스팅**: [Dockerfile](Dockerfile)이 `PORT` 환경변수를 따르고, 시작할 때 `alembic upgrade head`를 실행해요.
- 실시간 브로커가 메모리에 있어서 **인스턴스는 1개**로 운영해야 해요. 여러 개로 늘리려면 `app/realtime/broker.py`를 Redis Pub/Sub 구현으로 바꾸면 돼요(같은 인터페이스).

## 콘텐츠·약관 원칙

- 퍼블릭 도메인이 아닌 본문은 저장·배포하지 않습니다. 트래커 도서는 메타데이터와 진행률만 저장해요.
- 알라딘 Open API는 법인 사업자의 도서정보 서비스 이용 제한 조항 때문에 사용하지 않습니다.
- 외부 검색 결과에는 원 출처 링크를 함께 제공합니다.

## 범위 밖 (다음 단계)

FCM 푸시 · 실제 배포 · 카카오톡 공유 SDK · Redis 다중 인스턴스 · 위키문헌 목차 문서 병합(PRD EXC-07) · 탈퇴·개인정보 파기 흐름. 근거는 [GOAL.md](GOAL.md)와 [결정 로그](.grill/phase2-6-python-build.md)에 있어요.

> Phase 1까지 함께 있던 Spring Boot 인증 서버(PR #1)는 같은 기능(이메일 가입·로그인, 비밀번호 해시, 세션 교체, CSRF, 중복 이메일 차단)을 FastAPI로 옮기고 삭제했어요. 원래 코드는 git 기록(`dc3a321`)에 남아 있습니다.
