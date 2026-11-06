"""메일 보내기 — Resend HTTP API. RESEND_API_KEY가 없으면 보내지 않고 로그에 남긴다(로컬·시연용)."""

import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger("haedok.mail")
RESEND_URL = "https://api.resend.com/emails"


async def send_signup_code(client: httpx.AsyncClient, email: str, code: str) -> bool:
    """가입 인증 코드를 보낸다. 실제로 보냈거나 로그로 대신했으면 True, 발송이 실패하면 False."""
    settings = get_settings()
    if not settings.resend_api_key:
        log.warning("RESEND_API_KEY 없음 — %s 의 가입 인증 코드: %s", email, code)
        return True
    payload = {
        "from": settings.resend_from,
        "to": [email],
        "subject": f"[해독] 가입 인증 코드 {code}",
        "text": f"해독(偕讀) 가입 인증 코드는 {code} 이에요.\n10분 안에 입력해 주세요.",
        "html": (
            '<div style="font-family:sans-serif;line-height:1.6">'
            "<p>해독(偕讀) 가입 인증 코드예요.</p>"
            f'<p style="font-size:28px;font-weight:700;letter-spacing:6px">{code}</p>'
            "<p>10분 안에 입력해 주세요. 직접 요청하지 않았다면 이 메일을 무시해도 돼요.</p></div>"
        ),
    }
    try:
        r = await client.post(
            RESEND_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )
    except httpx.HTTPError as exc:
        log.error("Resend 요청 실패: %s", exc)
        return False
    if r.status_code >= 400:
        log.error("Resend 응답 %s: %s", r.status_code, r.text[:300])
        return False
    return True
