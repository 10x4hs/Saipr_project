# Grill: 고도화 — 부드러운 모션 + 최대한의 웹 기술
Date: 2026-10-20

> 목표 모드(/goal)로 진행해 사용자에게 멈춰 묻지 않았다. 질문 대신 지금까지의 결정·피드백과
> 조사 3건(docs/research/advanced-web-2026.md)으로 답을 정했고, 사용자가 바꿀 수 있는 가정은 아래에 드러냈다.

## Intent
수행평가 시연에서 "진짜 앱 같다"는 인상을 주도록, 승인된 Glass v2 화면 위에 부드러운 모션과 최신 웹 기술(설치·오프라인·푸시·읽어 주기 등)을
최대한 얹는다. 기술은 '보여 주기'에서 끝나지 않고 독서 경험에 실제로 쓸모가 있어야 한다.

## Constraints
- Glass v2 시안의 모습은 바꾸지 않는다 (사용자가 직전에 승인) — 모션·기술은 그 위에 더한다.
- 빌드 단계 없음(바닐라 JS·CSS), 외부 계정·유료 키 없음, 최대한 Python(서버 쪽은 FastAPI).
- 지원하지 않는 브라우저에서는 조용히 원래대로 동작(점진적 향상). `prefers-reduced-motion`·`prefers-reduced-transparency` 존중.
- 기존 규칙(체류시간·스포일러 가드)과 테스트 100개, CI는 그대로 통과해야 한다.

## Key decisions
- Decision: 페이지 이동은 문서 간 View Transitions(탭 바는 고정, 탭 방향에 따라 좌우 슬라이드, 책 표지는 검색→상세로 모핑). Reason: 서버 렌더링 앱을 네이티브처럼 만드는 가장 큰 효과를 CSS 몇 줄로(Chrome 126+, Safari 18.2+). Alternative considered: SPA로 바꾸기(빌드·재작성 필요).
- Decision: 모든 움직임은 `linear()` 스프링 곡선 3종(smooth·ios·bouncy)과 transform/opacity만 쓴다. Reason: 저가 안드로이드에서도 60fps. Alternative considered: JS 애니메이션 라이브러리.
- Decision: Liquid Glass는 '빛 반사가 손가락·기울기를 따라오는 하이라이트'를 모든 브라우저에, SVG 굴절(feDisplacementMap)은 Chromium에서 탭 바·리더 상단바 2곳에만. Reason: Safari/Firefox는 backdrop-filter의 SVG 필터를 렌더링하지 않음, 굴절은 비용이 큼.
- Decision: PWA(설치·앱 아이콘·오프라인으로 읽은 쪽 다시 읽기) + VAPID 웹 푸시(pywebpush, Firebase 계정 없음) + 배지 + 화면 꺼짐 방지 + 한국어 읽어 주기 + 탭 하나만 시간 재기(Web Locks) + Speculation Rules 미리 렌더링. Reason: 조사의 '임팩트×계정 없이 가능' 상위 8개.
- Decision: 리더에 남은 시간 칩(내 속도 학습), 타이포그래피 설정(글꼴·줄간격·문단 간격), 테마 아이보리·세피아·다크, 집중 모드. Reason: Kindle·Apple Books·리디 공통 패턴.
- Decision: 경쟁은 불안하지 않게 — 빨간 카운트다운 없음, 25·50·75% 이정표 축하, 연속 읽기는 부드럽게 표시. Reason: Apple Books의 '부드러운 목표' 패턴.

## Surfaced assumptions
- 시연은 노트북 Chrome(가장 많은 기능이 켜짐) + 가능하면 안드로이드 폰. iPhone 웹 푸시는 홈 화면에 설치해야만 된다.
- 웹 푸시·서비스 워커·폰에서의 설치는 HTTPS가 필요하다(localhost는 예외). 폰 시연은 계정 없는 터널(예: cloudflared quick tunnel)로 가능.
- 진동(햅틱)은 안드로이드만, 배지는 설치된 데스크톱 앱·iOS 홈 화면 앱만 — 없는 곳에서는 조용히 생략.

## Out of scope
- 쪽 넘김(페이지) 모드, 함께 밑줄(익명 집계), 백그라운드 동기화 — 이번에는 넣지 않음.
- Workbox 등 빌드가 필요한 도구.
