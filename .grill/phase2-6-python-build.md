# Grill: Phase 2~6 Python 구현 (수행평가)
Date: 2026-10-20

## Intent
수행평가로 함께읽기 MVP를 끝까지 만든다. 선생님 앞에서 브라우저로 방 만들기 → 친구 입장 → 진행률·반응 실시간 표시까지 시연하고, 코드·테스트·문서도 함께 제출한다.

## Constraints
- 최대한 Python. 서버는 FastAPI 하나로 통일한다.
- 시연 PC에 Docker가 없어도 `uvicorn` 한 줄로 실행돼야 한다.
- 외부 키(소셜 로그인, FCM, 호스팅)가 없어도 핵심 시연은 전부 동작해야 한다.

## Key decisions
- Decision: Spring Boot 인증 서버를 FastAPI로 옮기고 Java 코드는 삭제. Reason: 서버가 하나여야 실행·시연이 쉽고 "최대한 Python"에 맞음. Alternative considered: Java 보존 / Java로 로그인 유지.
- Decision: 프론트는 FastAPI + Jinja2 템플릿, 실시간 부분만 작은 JS(WebSocket·체류시간 측정). Reason: 설치가 가볍고 시연 때 안 깨짐. Alternative considered: Reflex(무거운 Node 빌드), Streamlit(실시간 리더에 부적합).
- Decision: 이메일 가입·로그인을 기본으로, 카카오·구글·네이버 OAuth는 `.env`에 키가 있을 때만 버튼 노출. Reason: 키 없이도 시연 가능. Alternative considered: 이메일만 / 키 발급 후 실제 연동.
- Decision: DB 기본값은 SQLite, Docker Compose에서는 Postgres. Reason: 시연 PC 의존성 최소화.
- Decision: 디자인은 기존 A(Glass)·B(Paper) 대신 refs.gallery experimental 카테고리 조사 결과로 새 방향. Reason: 사용자 선택.
- Decision: Phase 6는 앱 내 알림함(+WebSocket 실시간) + 배포 설정 파일까지. FCM·실제 배포는 제외. Reason: 외부 계정 필요.
- Decision: 결과물은 새 브랜치에 Phase별 커밋 후 PR. Reason: 팀 리뷰·커밋 이력이 평가에 유리.

## Surfaced assumptions
- Redis(브로커·리더보드)는 단일 인스턴스 MVP에서 인메모리 브로커·DB 집계로 대체해도 PRD의 인터페이스는 유지된다.
- 시연 네트워크에서 외부 도서 API가 막힐 수 있으므로 퍼블릭 도메인 샘플 도서를 시드 데이터로 넣어둔다.

## Out of scope
- FCM 푸시, 실제 호스팅 배포, 카카오톡 공유 SDK, 상용 본문.
