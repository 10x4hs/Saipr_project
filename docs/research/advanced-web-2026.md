# 조사: 부드러운 모션 · 최신 웹 기술 · 독서 UX (2026-10)

함께읽기 고도화 전에 조사한 내용과, 실제로 반영한 위치예요. 신뢰도는 높음/중간/낮음으로 표시했어요.

## 1. 모션

| 기술 | 지원 | 반영 | 신뢰도 |
|---|---|---|---|
| 문서 간 View Transitions (`@view-transition { navigation: auto }`) | Chrome·Edge 126+, Safari 18.2+, Firefox는 같은 문서 전환만 | 모든 페이지 이동 · 탭 방향 슬라이드 · 책 표지 모핑 (`motion.css`, `motion.js`) | 높음 |
| `pageswap` / `pagereveal` 이벤트로 전환 종류(앞/뒤) 지정 | Chrome 123+, Safari 18.2+ | 탭 순서로 좌우 방향 결정 | 높음 |
| `linear()` 스프링 곡선 | Baseline(2023~) | `--spring-smooth / -ios / -bouncy` 토큰 | 높음 |
| 스크롤 연동 애니메이션 (`animation-timeline: view()`) | Chrome 115+, Safari 26, Firefox 플래그 | 카드가 스크롤로 들어올 때 떠오름 (`@supports`로 감쌈) | 중간~높음 |
| `@starting-style` 등장 애니메이션 | Chrome 117, Safari 17.5, Firefox 129 | 토스트·시트·카드 첫 등장 | 높음 |
| 바텀 시트 끌어서 닫기 (포인터 + 속도) | 전부 | 반응·설정 시트 | 높음 |
| 진동 `navigator.vibrate` | 안드로이드만 (iOS 없음) | 반응·투표 때 짧은 진동, 없으면 생략 | 높음 |

성능 규칙: transform/opacity만 애니메이션, `backdrop-filter`는 한 화면에 2~3개 표면만 실제 흐림, `will-change`는 움직이는 동안만,
`content-visibility: auto`로 긴 본문 렌더링 절약, `prefers-reduced-motion`이면 움직임 대신 페이드.

출처: caniuse cross-document-view-transitions · developer.chrome.com/docs/web-platform/view-transitions/cross-document ·
webkit.org/blog/16301 · MDN `linear()` · developer.chrome.com/docs/css-ui/scroll-driven-animations · caniuse vibration · web.dev content-visibility

## 2. Liquid Glass (Apple iOS 26 스타일)

- SVG `feDisplacementMap`을 `backdrop-filter: url(#f)`로 쓰는 진짜 굴절은 **Chromium만** 렌더링해요. Safari·Firefox는 무시(WebKit 버그 #245510, #313914). — 신뢰도 높음
- `CSS.supports`는 거짓 양성이 있어 엔진으로 판별해요.
- 반영: 빛 반사 하이라이트가 포인터·기울기(DeviceOrientation, iOS는 탭으로 권한 요청)를 따라오는 효과는 모든 브라우저, 굴절은 Chromium의 탭 바·리더 상단바 2곳만 (`liquid.js`).
- 참고 구현: kube.io "Liquid Glass with CSS & SVG"(스넬 법칙 변위 맵), liquid-glass-js(캔버스 변위 맵), rdev/liquid-glass-react.

## 3. 웹 플랫폼 기능

| 기능 | 지원 | 반영 | 신뢰도 |
|---|---|---|---|
| PWA 매니페스트 + 서비스 워커 | 전부 (iOS는 공유 → 홈 화면에 추가) | 설치, 앱 셸 캐시, 읽은 쪽 오프라인 읽기, 오프라인 화면 (`/sw.js`, `/manifest.webmanifest`) | 높음 |
| 웹 푸시 (VAPID, Firebase 계정 없음) | Chrome·Firefox·Edge, iOS 16.4+ 홈 화면 앱 | 서버가 VAPID 키를 직접 만들고 `pywebpush`로 전송, 알림함과 같은 규칙(방해 금지·하루 5건) | 높음 |
| 배지 `setAppBadge` | 설치된 데스크톱 앱, iOS 홈 화면 앱 (안드로이드 없음) | 안 읽은 알림 수 | 높음 |
| 화면 꺼짐 방지 Wake Lock | Chrome 84+, iOS 16.4+ | 리더를 보는 동안 | 높음 |
| 한국어 읽어 주기 `speechSynthesis` | 전부 (ko-KR 음성은 기기마다 다름) | 문장 단위로 읽고 읽는 문장 강조 (`boundary` 이벤트는 불안정해서 문장마다 발화) | 중간 |
| Web Locks (`navigator.locks`) | Baseline | 같은 책을 탭 여러 개로 열어도 시간은 한 탭만 잼 | 높음 |
| Speculation Rules 미리 렌더링 | Chromium (Safari 없음, 무해) | 홈·검색·읽기방·리그·책 상세 링크 | 높음 |
| `navigator.storage.persist()` | Chrome, Firefox, Safari 17+ | 오프라인 저장을 지우지 않게 요청 | 중간 |

주의: 서비스 워커·푸시·폰 설치는 HTTPS가 필요해요(localhost 예외). 애플 푸시는 `sub`에 진짜 도메인 메일이 필요해요(`localhost`면 403).

출처: RFC 8292 (VAPID) · webkit.org "Web Push for Web Apps on iOS" · developer.chrome.com/docs/capabilities/web-apis/badging-api ·
caniuse wake-lock · MDN SpeechSynthesisUtterance · caniuse wf-speculation-rules · pywebpush issue #175

## 4. 독서 UX (Kindle · Apple Books · 리디 · 밀리의서재 · Readwise)

반영한 것:
1. **남은 시간 칩** — 내가 실제로 읽는 속도(글자/분)를 기기에 학습해 "이 쪽 약 N분 · 끝까지 약 M분". 2분 넘게 머문 구간은 딴짓으로 보고 제외. (Kindle)
2. **타이포그래피 설정** — 글꼴(명조·바탕·고딕), 글자 크기 4단계, 줄간격, 문단 간격. CSS 변수로 즉시 적용.
3. **테마** — 아이보리 · 세피아 · 다크(#1C1B19 / #D8D2C4, 순백 글씨 아님).
4. **집중 모드** — 화면 장식을 숨기고 지금 문단 말고는 흐리게.
5. **부드러운 목표** — 연속 읽기 일수 칩, 25·50·75% 이정표 축하, 빨간 카운트다운·손실 표현 없음. (Apple Books)
6. **함께 읽는 레이스** — 팀 합계 막대("우리 함께 N청크")를 먼저 보여 줌.

하지 않은 것: 쪽 넘김 모드, 익명 '함께 밑줄', 오디오 백그라운드 재생 약속.
