<div align="center">

# 제목: 미정

**쉬운 독서를 위해**

같은 책을 각자의 속도로 읽으면서 친구의 진행률과 문단 반응이 실시간으로 겹쳐 보이고,
팀을 짜서 공정한 페이지 레이스로 경쟁합니다.

 **[PRD](docs/PRD.md)** · [아키텍처](docs/architecture.md) · [GOAL](GOAL.md) · [Figma](https://www.figma.com/design/mp2nKNmBdJ7Dg2rc2p9rht)

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

## 지금 되는 것

> 시연 영상: `docs/demo/함께읽기-시연.mp4` (56초, 저장소에는 올리지 않음 — 아래 "시연 영상 만들기"로 다시 만들 수 있어요)

| 화면 | 기능 |
|---|---|
| 로그인 · 가입 | 사진 한 장 위 유리 입력칸 하나씩 (이메일 → 비밀번호). BCrypt·CSRF·30분 세션 |
| 홈 | 인기 고전이 세 권씩 늘어선 격자가 스크롤하면 위쪽 롤러에 감기듯 **3D로 말려 올라감**. 오른쪽 위 메뉴로 목록 보기 전환 |
| 탐색 · 검색 | 퍼블릭 도메인 396권(위키문헌 296 · 구텐베르크 100), 장르 칩·필터, 외부 검색 |
| 리더 | 화면 크기로 쪽을 나눠 **3D 페이지 넘김**, 서버가 잰 체류시간으로만 "읽음", 문단을 눌러 반응(이모지 5종·한 줄 글) |
| 대결 | 6자리 초대 코드·공유, 검증된 쪽 수로 순위, WebSocket으로 실시간 갱신·추월 애니메이션 |
| 함께 읽기 | 같은 방 친구의 진행·반응 알림, **스포일러 가드**(내가 아직 못 읽은 쪽의 반응은 개수만) |
| 서재 · 올리기 | 읽는 중·다 읽음·내 파일, DRM 없는 EPUB·PDF·TXT 올리기(본문은 나만) |
| 화면 꾸미기 | 자동·밝게·어둡게, 배경 30종(기본·책·자연·날씨·우주, 캔버스 비·눈·별), 강조 색 12종 — 계정에 저장 |

## 저장소 구성

| 경로 | 내용 |
|---|---|
| `app/api/` | JSON API · WebSocket (`books`, `me`, `social`) |
| `app/web.py`, `app/templates/`, `app/static/` | 서버 렌더링 모바일 웹 앱 (Jinja2 + 작은 바닐라 JS) |
| `app/services/` | 검색 · 청크화 · 체류시간 · 서재 · 업로드 파싱 · 대결 · 반응 |
| `app/realtime.py` | 책 단위 인메모리 브로커 (여러 대로 늘리면 Redis Pub/Sub로 교체) |
| `app/data/` | 서가 카탈로그 · 인기 고전 순서 |
| `scripts/` | `build_catalog.py`(퍼블릭 도메인 수집), `fetch_covers.py`(표지 이미지 — 프로토타입 전용) |
| `migrations/`, `tests/` | Alembic · pytest (네트워크 0) |

## 빠른 시작

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/fetch_covers.py      # 선택: 표지 이미지 (없으면 생성 표지)
cp .env.example .env                # SECRET_KEY는 운영에서 반드시 바꾸기
docker compose up --build           # Postgres + 앱 (http://localhost:8000)
```

DB 없이 바로 보기(SQLite):

```bash
export DATABASE_URL="sqlite+aiosqlite:///$PWD/scratch-dev.db" DWELL_SCALE=0.06   # 시연용: 체류시간 6%
python -c "import asyncio;from sqlalchemy.ext.asyncio import create_async_engine;from app import models;from app.db.base import Base
async def m():
    e=create_async_engine('$DATABASE_URL')
    async with e.begin() as c: await c.run_sync(Base.metadata.create_all)
asyncio.run(m())"
uvicorn app.main:app --port 8011
```

검증: `pytest -q` · `ruff check .` — 완료 기준과 현재 상태는 [GOAL.md](GOAL.md).

## 로드맵

- [x] Phase 0–1 — 스캐폴딩 · 도서 소스 · 통합 검색 · 청크화
- [x] 계정 · 서재 · 리더(3D 넘김) · 업로드 · 화면 꾸미기
- [x] Phase 3 — 대결방 · 초대 코드 · 실시간 · 문단 반응 · 스포일러 가드
- [ ] 소셜 로그인 · 트래커 모드(상용 도서 수동 진행률)
- [ ] 한줄평 배틀 · 포인트 · 팀 리그 · 푸시 · 배포

## 콘텐츠·약관 원칙

- 본문은 두 경로로만 들어옵니다: 퍼블릭 도메인 소스(위키문헌·구텐베르크), 그리고 사용자가 직접 올린 DRM 없는 EPUB·PDF·TXT. 올린 파일의 본문은 올린 브라우저에서만 열리고, 다른 사람에게는 위치·진행률·반응만 공유됩니다. DRM 해제나 웹 크롤링으로 본문을 모으지 않습니다.
- 퍼블릭 도메인이 아닌 본문은 저장·배포하지 않습니다.
- 알라딘 Open API는 법인 사업자의 도서정보 서비스 이용 제한 조항 때문에 사용하지 않습니다.
- 외부 검색 결과에는 원 출처 링크를 함께 제공합니다.
- 책 표지 이미지(`scripts/fetch_covers.py`)는 출시하지 않는 시연용으로만 받아 두고 저장소에 올리지 않습니다. 출시 전에는 라이선스가 있는 표지 API로 바꿔야 합니다.
