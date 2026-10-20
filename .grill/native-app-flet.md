# Grill: 함께읽기를 진짜 앱으로 (Flet)
Date: 2026-10-20

## Intent
웹 결과물이 "앱 같지 않고 어색하며 기능이 부족하다"는 피드백. 마감(1~2일)이 촉박해도 **내일 출시할 수 있는 품질**의 네이티브 앱으로 다시 만든다.

## Constraints
- 최대한 Python — 앱도 Python(Flet 1.0).
- 출시 품질: 범위를 줄여서 맞추지 않는다. 네트워크가 흔들려도 앱이 버티고, 받아 둔 책은 오프라인으로 읽힌다.
- 안드로이드 APK까지 빌드해서 실제(에뮬레이터) 기기에서 확인한다.

## Key decisions
- Decision: Flet 독립 클라이언트 앱 + 기존 FastAPI(API 확장). Reason: 네이티브 느낌·오프라인·Python. Alternative considered: React Native(Expo, TypeScript), 웹 SPA+PWA, 서버 구동형 Flet(연결 끊기면 멈춤).
- Decision: 디자인은 앱 안에서 고른다 — Glass(시안) · Material 3 · Cupertino, 각각 라이트/다크. Reason: 사용자 요청("선택할 수 있게").
- Decision: 기능 추가 — 친구·소셜(팔로우·피드·응원·방 채팅), 독서 기록·통계(잔디·주간 그래프·목표·배지), 책 정보(위키백과 소개·장르·인기·더 많은 공개 도서), 밑줄·메모 모음(카드 공유). Reason: 사용자가 네 가지 모두 선택.
- Decision: 웹은 초대 링크 미리보기·로그인만 남기고 정리. Reason: 앱이 주인공, 유지보수 절반.
- Decision: 리더는 쪽 넘김(청크=쪽, PageView). Reason: 앱다운 독서 경험, 현재 쪽이 분명해 체류시간 측정도 정확.

## Surfaced assumptions
- 폰에서 서버에 닿으려면 같은 와이파이의 노트북 IP나 배포 주소가 필요 → 앱 첫 화면에서 서버 주소를 정한다.
- APK 빌드에는 JDK 17과 Flutter SDK가 필요(Flutter는 flet build가 받아 옴, JDK는 설치 필요).
- 한국어 읽어 주기(TTS)는 Flet 기본 기능에 없어 이번 앱에서는 뺀다(웹 버전에는 있었음).

## Out of scope
- iOS 실기기 빌드(인증서 필요), 스토어 등록, 결제.
