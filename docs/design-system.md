# 디자인 시스템 — 함께읽기 · Index (색인)

- **기준 구현:** [app/web/static/css/index.css](../app/web/static/css/index.css) (토큰 · 컴포넌트 전부) + [app/web/templates/](../app/web/templates/)
- **화면:** [docs/images/index-01~06](images/) — 실제 앱을 브라우저로 렌더링한 캡처
- **이전 시안(보관):** Glass v2 · Paper B → [docs/mockups/archive/](mockups/archive/). 두 시안 모두 채택하지 않고 아래 방향으로 결정했습니다.

## 왜 Index인가

refs.gallery의 **Experimental** 카테고리를 실제 브라우저로 조사해(사이트 설명문이 아니라 각 사이트의 computed style을 확인) 공통점을 뽑았습니다.

| 레퍼런스 | 가져온 것 |
|---|---|
| [Nodeck](https://nodeck.online) | 라임 `#DEF915` · 핑크 `#FF87AB` 블록 채움, 키네틱 마키 |
| [No Art Music](https://noartmusic.com) | `EVENTS [5]` 같은 괄호 카운터, 모노 대문자 내비 |
| [studio pointer\*](https://pointer.click) | 흰 바탕의 절제, 인덱스 리스트, 강조색은 하나만 |
| [OKOK Services](https://okok.services) | 흑·백·회색 톤, 텍스트 리스트 중심 레이아웃 |
| [Gentle Systems](https://www.gentle.systems) | 날짜 스탬프 로그형 피드 → 읽기방 활동 로그 |
| [MUZZIN+SAMIRI](https://www.benjaminmuzzin.ch) | 화면을 채우는 초대형 워드마크 → 레이스 점수 숫자 |
| [Commute / Metronome](https://commute.dataveyes.com) | 데이터 시각화 눈금 → 읽기방 진행률 눈금자 |
| [52 Weeks of Obsessions](https://www.thomasmoes.com/52obsessions) | 번호 붙은 주차 아카이브 → 프로필 52주 그리드 |

이 카테고리의 공통점은 흑백 바탕에 원색 1~2개, 모노스페이스 메타 라벨, 극단적인 글자 크기 대비, 번호를 붙인 인덱스 구조예요.
독서 앱에 그대로 쓰면 리더가 읽기 어려워지므로, **실험적인 요소는 리더의 여백(문단 번호 · 반응 카운터)에만 두고 본문은 장식 없이** 둡니다.

## 원칙

1. **흑백 + 헤어라인.** 면은 오프화이트, 구획은 1px 검정 선. 그림자·둥근 모서리·그라디언트를 쓰지 않는다.
2. **라임·핑크는 채움 전용.** 밝은 배경 위 글자색으로 쓰지 않는다(대비 부족). 라임 = 1위·내 것·검증됨, 핑크 = 반응·팀·알림.
3. **숫자는 크게, 라벨은 작게.** 점수·진행률은 Black Han Sans 초대형, 메타 정보는 12px 모노 대문자.
4. **모든 목록은 색인.** `01 02 03` 번호, `[04]` 괄호 카운터.
5. **리더는 조용하게.** 본문 Noto Serif KR 18px · 행간 1.8 · 한 줄 최대 34em. 모션 없음.
6. **스포일러는 자물쇠.** 잠긴 반응은 내용 없이 `🔒 앞에서 N개의 반응이 기다리고 있어요`.
7. **카카오 버튼만 예외.** 브랜드 가이드의 노랑 `#FEE500`.

## 토큰

| 토큰 | 값 | 용도 · 대비(WCAG, 배경 `#F2F2EF` 기준) |
|---|---|---|
| `--bg` | `#F2F2EF` | 기본 배경 (차가운 오프화이트) |
| `--paper` | `#FFFFFF` | 입력창·카드 hover |
| `--ink` | `#111111` | 본문 · 선 — **16.8:1** |
| `--muted` | `#5E5E5A` | 보조 텍스트 — **5.8:1** (AA) |
| `--lime` | `#DEF915` | 채움 전용, 위 검정 글자 **15.9:1** |
| `--pink` | `#FF87AB` | 채움 전용, 위 검정 글자 **8.4:1** |
| `--blue` | `#312DFB` | 링크 — **6.5:1** |
| 리더 배경 | 흰색 `#FFF` / 파치먼트 `#F4ECD8`(잉크 `#2B1703`) / 다크 `#161616`(잉크 `#E9E9E4`) | 사용자 설정 3종 |

## 타이포그래피 (Google Fonts, 한글 지원)

| 역할 | 글꼴 | 크기 |
|---|---|---|
| 디스플레이 · 점수 | Black Han Sans | `clamp(44px, 9vw, 120px)`, 점수 `clamp(64px, 14vw, 200px)` |
| UI 본문 | IBM Plex Sans KR | 16px / 1.6 |
| 리더 본문 | Noto Serif KR | 16 · **18(기본)** · 20 · 23px 4단계 / 1.8 |
| 라벨 · 숫자 | IBM Plex Mono (한글은 Plex Sans KR로 대체) | 12~13px 대문자 |

## 컴포넌트 (CSS 클래스)

| 컴포넌트 | 클래스 | 쓰는 곳 |
|---|---|---|
| 인덱스 리스트 | `.index` `.row` (`.no` · `.title` · `.meta`) | 홈 읽는 중, 서재, 팀, 알림 |
| 그리드 셀 | `.grid` `.cell` (`.lime` `.pink`) | 읽기방 카드, 배틀 카드 |
| 마키 티커 | `.ticker` `.ticker-track` | 홈 상단 친구 진행률 (`prefers-reduced-motion`이면 정지) |
| 진행 바 | `.bar > i` | 모든 진행률 |
| 눈금자 | `.ruler` `.marker` (`.me`) | 읽기방 멤버 위치 (실시간 이동) |
| 순위표 | `.table` (`tr.first` 라임) | 방 안 레이스, 리그 |
| 리더 | `.page` `.chunk-head` `.pno` `.para` `.side` `.rx` `.locked-note` | 리더 3열 그리드(문단 번호 · 본문 · 반응) |
| 액션 시트 | `.sheet` `.emoji-row` | 문단 탭 → 이모지 5종 · 한줄평 |
| 칩 · 버튼 | `.chip` `.btn` (`.primary` `.lime` `.pink` `.kakao`) | 전역 |

## 화면별 적용

| 화면 | 적용 |
|---|---|
| 홈 | `지금 읽는 중 [01]` 디스플레이 + 인덱스 리스트, 상단 라임 마키(친구 진행률) |
| 검색 | 초대형 검색 입력, 헤어라인 표, 전문 소스 칩은 라임 |
| 리더 | 장식 없는 본문. 왼쪽 `¶3` 문단 번호, 오른쪽 `[+2]` 핑크 반응 카운터, 청크 머리에 친구 이니셜 점 |
| 읽기방 | 가로 눈금자 위 멤버 마커가 WebSocket으로 움직임, `12:11 · 준호 → 18%` 모노 로그 |
| 레이스 | 팀 평균 점수 200px 숫자, 앞선 팀 라임 채움 |
| 팀 · 프로필 | 핑크 팀 헤더, 52주 아카이브 그리드 |

## 접근성

- 본문 16px 이상, 리더 기본 18px. 대비는 위 표 전부 AA 이상(본문은 AAA).
- 터치 타깃 44×44px 이상(`.btn`, 내비, 이모지 버튼 48px).
- 키보드 포커스 `3px solid --blue`. 마키는 `prefers-reduced-motion`에서 멈춤.
- 640px 이하에서 리더는 2열(문단 번호 · 본문)로 바뀌고 반응 카운터는 문단 아래로 내려감. 페이지 가로 스크롤 없음.
