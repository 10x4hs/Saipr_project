# 해독 개선 설계 (2026-11-06)

Polling (~5s) is the realtime baseline; WebSocket is opportunistic.

## Worker A — auth & landing
1. PWA manifest + service worker; TWA APK via Bubblewrap at /static/haedok.apk; download CTA on landing.
2. Signup email verification: 6-digit code, Resend (RESEND_API_KEY), log fallback; 10 min TTL, 5 tries.
9. "비밀번호 한 번 더" -> "비밀번호 확인".
11. Login background: prettier blurred glassmorphism.

## Worker B — reader
3. Back = history.back, fallback /library.
4. Read threshold = 30s * (chunk chars / baseline chars at font 18); server pace.py validates by chars.
5. Page jump (slider/number); jumped pages not marked read.
6. Resume at verified+1.

## Worker C — theme/UI
8. Fix customize UI breakage.
10. Background luminance tag -> text color vars; no dark text on dark bg (ranklist).
12. Home book rail: touch-drag a book (e.g. 싯다르타) to pull it forward — drag scrolls the rail, same motion as current scroll.

## Worker D — race
7. Presence "친구가 이 쪽을 읽고 있어요" (reader + race) via static/presence.js.
- Live progress race bar with overtake animation.
- Quote sharing to race feed.
New tables: RacePresence, RaceQuote.

## Merge order: C -> A -> B -> D. Each: ruff + pytest + new tests.
