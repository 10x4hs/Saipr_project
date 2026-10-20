"""비밀번호 해시 · 입력 검증 · CSRF 토큰.

Spring Boot 버전(BCrypt cost 12)을 대체한다. 외부 의존성 없이 표준 라이브러리 scrypt를 쓴다.
"""

import hashlib
import hmac
import re
import secrets

# scrypt 파라미터 (OWASP 권장 최소치: N=2^17, r=8, p=1)
_N, _R, _P = 2**17, 8, 1
_MAXMEM = 256 * 1024 * 1024

MIN_PASSWORD_LEN = 8
# Spring 버전과 같은 상한. 아주 긴 입력으로 해시 비용을 키우는 공격도 막는다.
MAX_PASSWORD_BYTES = 72

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str | None:
    if len(email) > 255 or not _EMAIL.match(email):
        return "이메일 형식이 올바르지 않아요."
    return None


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LEN:
        return f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 해요."
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return f"비밀번호가 너무 길어요 (UTF-8 기준 {MAX_PASSWORD_BYTES}바이트 이하)."
    return None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    calc = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), maxmem=_MAXMEM
    )
    return hmac.compare_digest(calc.hex(), digest)


# 사용자가 없을 때도 같은 시간만큼 해시를 계산해, 응답 시간으로 가입 여부를 알 수 없게 한다.
DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(expected: str | None, given: str | None) -> bool:
    return bool(expected and given and hmac.compare_digest(expected, given))
