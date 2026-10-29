<div align="center">

# 제목: 미정

**쉬운 독서를 위해**

같은 책을 각자의 속도로 읽으면서 친구의 진행률과 문단 반응이 실시간으로 겹쳐 보이고,
팀을 짜서 공정한 페이지 레이스로 경쟁합니다.

 **[PRD](docs/PRD.md)** · [디자인 시스템](docs/design-system.md) · [아키텍처](docs/architecture.md) · [GOAL](GOAL.md) · [Figma](https://www.figma.com/design/mp2nKNmBdJ7Dg2rc2p9rht)

<img src="docs/images/01-home.png" width="200" alt="홈"> <img src="docs/images/03-reader.png" width="200" alt="리더"> <img src="docs/images/b-03-reader.png" width="200" alt="리더 시안 B">

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

- **하이브리드 콘텐츠** — 저작권 만료작(위키문헌·Gutendex)은 앱 안 리더로 전문을 읽고, 시판 도서는 카카오·네이버·Google Books 메타데이터와 수동 진행률로 기록합니다. 본문 제공 소스는 코드에서 화이트리스트로 강제합니다.
- **청크 = 공통 위치** — 판본·기기마다 달라지는 "페이지" 대신 본문을 결정적으로 나눈 청크를 좌표로 씁니다. 그래서 반응이 모든 사람에게 같은 문단에 겹칩니다.
- **스포일러 가드** — 내가 아직 안 읽은 위치의 반응은 내용 없이 "앞에서 N개의 반응이 기다리고 있어요"로만 보입니다.
- **체류시간 검증** — 청크 글자 수 대비 최소 체류시간을 서버가 판정해, 넘기기만 한 구간은 레이스 점수에서 빠집니다.

## 테마 선택

같은 6화면을 두 방향으로 만들었습니다. 

| | 홈 | 리더 | 레이스 |
|---|---|---|---|
| **A · Grass** | <img src="docs/images/01-home.png" width="180"> | <img src="docs/images/03-reader.png" width="180"> | <img src="docs/images/05-race.png" width="180"> |
| **B · Paper** | <img src="docs/images/b-01-home.png" width="180"> | <img src="docs/images/b-03-reader.png" width="180"> | <img src="docs/images/b-05-race.png" width="180"> |

## 저장소 구성

백엔드·프론트 모두 Python입니다.

| 경로 | 내용 | 스택 |
|---|---|---|
| `app/`, `migrations/`, `tests/` | 도서 검색·전문 청크화 API (PRD Phase 0–1) | Python 3.12 · FastAPI · SQLAlchemy · Alembic |
| `docs/` | PRD · 디자인 시스템 · 시안 목업(HTML) · 아키텍처 | |

> 백엔드는 Python(FastAPI) 하나로 통일했습니다. 이전 Spring Boot 세션 인증(PR #1)은 Phase 2에서 FastAPI로 옮깁니다(git 이력에 보존).

## 빠른 시작 — 도서 API (Python)

```bash
cp .env.example .env          # API 키는 선택 — 없으면 Google Books·위키문헌·Gutendex만 사용
docker compose up --build     # Postgres + API, 마이그레이션 자동 적용
```

```bash
# 검색 (여러 소스 병렬 조회, 실패한 소스는 errors에 표시)
curl "localhost:8000/api/v1/books/search?q=봄봄"

# 퍼블릭 도메인 전문 가져오기 → 청크 읽기
curl -X POST localhost:8000/api/v1/books/import \
     -H "Content-Type: application/json" \
     -d '{"source": "wikisource", "external_id": "봄봄"}'
curl localhost:8000/api/v1/books/1/chunks/0
```

API 문서는 서버 실행 후 <http://localhost:8000/docs>.

로컬 개발:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q          # 외부 네트워크 없이 실행 (httpx.MockTransport + in-memory SQLite)
ruff check .
uvicorn app.main:app --reload
```

| 환경 변수 | 필수 | 설명 |
|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://…` |
| `KAKAO_REST_API_KEY` | | 카카오 도서검색 (국내 1순위) |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | | 네이버 책 검색 (보조) |
| `GOOGLE_BOOKS_API_KEY` | | 없으면 낮은 쿼터로 동작 |
| `WIKISOURCE_LANG` | | 기본 `ko` |

## 로드맵

- [x] Phase 0 — 스캐폴딩 · DB · Docker · CI
- [x] Phase 1 — 도서 소스 어댑터 · 통합 검색 · 전문 청크화
- [ ] 세션 기반 회원가입·로그인 — Spring 버전(PR #1)을 FastAPI로 이식 (Phase 2)
- [ ] Phase 2 — 소셜 로그인 · 내 서재 · 리더 이벤트 · 트래커 모드
- [ ] Phase 3 — 읽기방 · WebSocket 진행률 동기화 · 문단 반응 · 스포일러 가드
- [ ] Phase 4 — 페이지 레이스 · 한줄평 배틀 · 포인트
- [ ] Phase 5 — 팀 · 주간 리그
- [ ] Phase 6 — 푸시 알림 · 배포

완료 기준은 [GOAL.md](GOAL.md)에 측정 가능한 형태로 정리되어 있습니다.

## 콘텐츠·약관 원칙

- 퍼블릭 도메인이 아닌 본문은 저장·배포하지 않습니다.
- 알라딘 Open API는 법인 사업자의 도서정보 서비스 이용 제한 조항 때문에 사용하지 않습니다.
- 외부 검색 결과에는 원 출처 링크를 함께 제공합니다.
