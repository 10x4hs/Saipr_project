# 함께읽기 네이티브 앱 — 설계 (2026-10-20)

> 결정 로그: [.grill/native-app-flet.md](../../.grill/native-app-flet.md)

## 목표

웹 화면을 버리고 **Python(Flet 1.0) 네이티브 앱**으로 다시 만든다. 기준은 "내일 스토어에 올려도 되는 품질".
안드로이드 APK + macOS 앱(시연용)으로 빌드한다. 서버(FastAPI)는 그대로 두고 앱이 쓸 API를 늘린다.

## 구조

```
app/      FastAPI 서버 — 기존 + 토큰 인증 · 친구 · 피드 · 채팅 · 통계 · 밑줄 · 책 정보 API
mobile/   Flet 앱 (Python)
  main.py          진입 · 라우팅(page.views 스택, 뒤로가기) · 테마 적용
  core/api.py      httpx 비동기 클라이언트(Bearer 토큰, 오류 → ApiError, 재시도)
  core/realtime.py WebSocket(재연결, 이벤트 구독)
  core/store.py    SharedPreferences(토큰·설정) + 파일 캐시(받아 둔 책 본문, 읽기 이벤트 큐)
  core/reading.py  체류시간 측정(현재 쪽 · 앱 생명주기) — 순수 로직, 단위 테스트
  ui/theme.py      Glass · Material 3 · Cupertino × 라이트/다크 — 공용 위젯 팩토리
  ui/widgets.py    표지, 아바타, 진행 막대, 섹션, 빈 화면, 스켈레톤(Shimmer)
  views/*.py       화면
mobile/tests/      순수 로직·API 클라이언트 테스트
```

- 웹(Jinja2)은 초대 링크 미리보기 + 로그인/가입/OAuth만 남기고 정리한다.
- 앱은 서버 주소를 첫 화면에서 정한다(같은 와이파이의 노트북 IP 또는 배포 주소).

## 화면 (하단 탭 5개: 홈 · 둘러보기 · 서재 · 함께 · 나)

| 화면 | 내용 |
|---|---|
| 시작 | 서버 주소 → 로그인 / 가입 (+ 데모 계정 빠른 로그인) |
| 홈 | 인사·연속 읽기·오늘 목표 링, 이어 읽기 히어로 카드(표지 Hero), 지금 읽는 친구들, 내 읽기방, 진행 중 레이스 |
| 둘러보기 | 검색, 장르(소설·시), 인기(읽는 사람 많은 순), 새로 들어온 책, 외부 검색(트래커) |
| 책 상세 | 표지, 제목·작가, 작품 소개·작가 소개(위키백과, 출처 표기), 읽는 사람 수, 읽은 친구, 읽기/담기/방 만들기/진행률 기록 |
| 리더 | 쪽 넘김(PageView, 청크=쪽), 탭하면 상·하단 바, 쪽 슬라이더, 설정(글자·줄간격·글꼴·종이/세피아/다크), 문단 탭 → 반응, 길게 누르기 → 밑줄+메모, 친구 위치, 스포일러 잠금, 화면 꺼짐 방지, 오프라인 본문, 남은 시간, 이정표 |
| 서재 | 읽는 중 · 읽고 싶은 · 완독 · **밑줄·메모**(책별, 카드 이미지로 공유) |
| 함께 | 피드(친구 활동, 응원하기) · 친구(코드/닉네임 추가, 프로필) · 읽기방(목록·입장·**채팅**·멤버 진행률·반응) · 리그(순위·팀·배틀) |
| 나 | 프로필, **통계**(오늘·이번 주 막대·12주 잔디·완독 수·연간 목표 링), 배지, 포인트·챌린지, 알림, 설정(테마 선택 Glass/Material/Cupertino, 라이트/다크, 스포일러 가드, 목표, 서버, 로그아웃) |

## API 계약 (앱이 쓰는 것 — 모두 `/api/v1`)

인증: `Authorization: Bearer <token>`. Bearer 요청은 CSRF 검사를 건너뛴다(쿠키가 없으므로).
기존 엔드포인트(도서·서재·이벤트·반응·방·팀·배틀·포인트·알림·푸시)는 그대로 Bearer로도 쓸 수 있어야 한다.

### 인증
- `POST /auth/token` `{email, password}` → `{token, user: Me}` (401 실패). `POST /auth/token/signup` `{nickname, email, password, password_confirm}` → 201 `{token, user}`.
- `DELETE /auth/token` → 204 (현재 토큰 폐기). 토큰은 DB에 해시로 저장, 만료 90일.
- `GET /auth/me` → `Me` = `{id, nickname, email, spoiler_guard, friend_code, bio, avatar_color, daily_goal_minutes, yearly_goal_books}`
- `PUT /auth/me/profile` `{nickname?, bio?, daily_goal_minutes?, yearly_goal_books?, spoiler_guard?}` → `Me`
- WebSocket: `/ws/rooms/{id}?token=…`, `/ws/me?token=…` (토큰이 있으면 Origin 검사 생략)

### 책
- `GET /books?genre=&sort=popular|new&limit=` → `[BookCard]` — 앱에 있는 책(전문·트래커).
  `BookCard` = `{id, title, author, genre, has_fulltext, total_chunks, cover_url, cover_color, readers}`
- `GET /books/{id}/info` → `BookCard + {description, author_bio, source_url, wiki_url, friends_reading: [UserMini], my_entry: Entry|null, total_chars}`
  (description·author_bio는 위키백과 요약을 서버가 받아 DB에 캐시. 오프라인이면 null)
- 기존: `GET /books/search`, `POST /books/import`, `POST /books/track`, `GET /books/{id}/chunks/{i}`(→ text, min_dwell_ms)

### 친구 · 피드
- `GET /users/search?q=` → `[UserMini + {is_following}]` (닉네임 부분 일치 또는 친구 코드 정확히)
- `GET /users/{id}` → `Profile` = `UserMini + {bio, is_following, followers, following, stats: {books_done, streak, minutes_week}, reading: [BookCard+progress_pct], highlights: [공개 밑줄 최근 5]}`
- `POST /users/{id}/follow` 204 · `DELETE /users/{id}/follow` 204 · `GET /me/following` `[UserMini]` · `GET /me/followers`
- `POST /users/{id}/cheer` 202 — 응원 알림(하루 같은 사람에게 1번)
- `GET /feed?before=<id>&limit=` → `[Activity]` = `{id, user: UserMini, kind, book: BookCard|null, data, created_at}`
  kind: `started` · `milestone`(data.pct 25/50/75) · `finished` · `highlight`(data.quote, data.note) · `joined_room`(data.room_name) · `badge`(data.title)
  내가 팔로우한 사람 + 나 자신의 활동. `UserMini` = `{id, nickname, avatar_color}`

### 읽기방 채팅
- `GET /rooms/{id}/messages?before=&limit=50` → `[Message]` = `{id, user: UserMini, body, created_at}` (오래된 → 새 순)
- `POST /rooms/{id}/messages` `{body}` (1~500자) → `Message`. WebSocket 방 채널에 `message.created` (본문 포함 — 채팅은 스포일러 가드 대상 아님)

### 통계 · 배지
- `GET /me/stats` → `{today_minutes, week: [{date, minutes, chunks}×7], heatmap: [{date, minutes}×84], streak, best_streak, books_done, books_done_year, yearly_goal_books, daily_goal_minutes, total_minutes, total_chunks, reactions, highlights}`
  분 = 인정된 체류시간(credited dwell) 합 ÷ 60000, KST 날짜 기준
- `GET /me/badges` → `[{code, title, description, icon, earned, earned_at|null, progress, goal}]` (첫 쪽 · 첫 완독 · 3/7/30일 연속 · 반응 10 · 밑줄 10 · 친구 3 · 레이스 승리 · 밤 독서)

### 밑줄 · 메모
- `POST /books/{id}/highlights` `{chunk_index, anchor, quote, note?, color: yellow|green|blue|pink, visibility: private|friends}` → `Highlight` (quote는 그 청크 본문에 있어야 함, 읽은 위치까지만)
- `GET /me/highlights?book_id=` → `[Highlight + {book: BookCard}]` · `DELETE /highlights/{id}` 204 · `PATCH /highlights/{id}` `{note?, color?, visibility?}`
- `GET /books/{id}/highlights?scope=friends` → 친구들의 공개 밑줄 (스포일러 가드 적용: 내 위치보다 뒤는 개수만 `{visible, locked_total}`)
- `friends` 공개 밑줄은 피드에 `highlight` 활동으로 남는다.

## 품질 기준 (완료 판정)

1. 서버 `pytest -q` 전부 통과, `ruff check .` 0, 새 API마다 테스트.
2. 앱 순수 로직(체류시간·큐·API 클라이언트) 테스트 통과.
3. macOS 앱으로 모든 화면을 실제로 띄워 3가지 테마 × 라이트/다크 스크린샷 확인.
4. APK를 빌드해 에뮬레이터에 설치·실행, 로그인 → 읽기 → 반응 → 채팅 → 통계까지 시나리오 통과.
5. 서버가 꺼져도 앱이 죽지 않고(오류 화면·재시도), 받아 둔 책은 계속 읽힌다.
