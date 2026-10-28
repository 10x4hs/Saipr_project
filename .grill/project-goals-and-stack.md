# Grill: 프로젝트 목적과 스택 정리
Date: 2026-10-28

## Intent
클라이언트 의뢰로 만드는 함께읽기 MVP를 통해 (1) vibecoding 수준과 (2) Python 활용을 보여준다. 평가자는 개발자이기도 한 선생님.

## Constraints
- 백엔드·프론트 모두 Python.
- 결과물 수준(A: 동작하는 기능)과 통제 수준(B: PRD → 코드 → 테스트 → CI 일관성)을 동시에 충족.

## Key decisions
- Decision: Java/Spring 인증 서버 제거, FastAPI로 단일화. Reason: Python 목적 + 스택 이원화는 개발자 평가자에게 통제 부족으로 보임. Alternative considered: Spring 인증 + FastAPI 도서 API 분리 운영 — 기각.
- Decision: Spring 세션 인증 명세(BCrypt cost 12, 이메일 정규화, 30분 세션, CSRF)는 Phase 2에서 FastAPI로 이식. 원본은 git 이력(dc3a321)에 보존.
- Decision: 프론트엔드는 Reflex (Python).

## Surfaced assumptions
- 개발자 평가자는 기능 개수보다 문서·테스트·CI의 일관성을 함께 본다.

## Open questions
- 디자인: A·B 시안 모두 확정하지 않고 새로 설계하기로 함 (별도 설계 세션 필요).
- 서비스 제목: 클라이언트와 상의 후 결정 (README는 "미정" 유지).
- 제출 마감과 클라이언트의 구체적 평가 기준.
