from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "saipr"
    database_url: str = "postgresql+asyncpg://saipr:saipr@localhost:5432/saipr"

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        """호스팅 Postgres(Neon 등)가 주는 postgres://…?sslmode=require 를 asyncpg 형식으로 바꾼다."""
        if v.startswith("postgres://"):
            v = "postgresql://" + v.removeprefix("postgres://")
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v.removeprefix("postgresql://")
        if v.startswith("postgresql+asyncpg://"):
            # asyncpg가 모르는 쿼리 인자(sslmode, channel_binding)를 정리한다 — 순서와 상관없이
            parts = urlsplit(v)
            query = []
            for key, val in parse_qsl(parts.query):
                if key == "channel_binding":
                    continue
                query.append(("ssl", val) if key == "sslmode" else (key, val))
            v = urlunsplit(parts._replace(query=urlencode(query)))
        return v

    # 외부 소스별 타임아웃. 한 소스가 느려도 통합 검색 전체가 막히지 않도록 짧게 둔다.
    http_timeout_seconds: float = 3.0

    # 키가 비어 있는 소스는 자동 비활성화된다 (registry.build_sources 참고).
    kakao_rest_api_key: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    google_books_api_key: str | None = None
    wikisource_lang: str = "ko"

    # 세션 쿠키 서명 키. 운영에서는 반드시 .env로 바꾼다
    secret_key: str = "dev-only-change-me"
    session_idle_minutes: int = 30
    cookie_secure: bool = False
    # 시연·로컬 테스트용 최소 체류시간 배율. 운영은 반드시 1.0
    dwell_scale: float = 1.0
    # 업로드 상한(MB). Vercel은 요청 본문을 4.5MB에서 끊으므로 배포에서는 4로 둔다
    max_upload_mb: int = 20
    # 가입 인증 메일(Resend). 키가 없으면 코드를 로그에만 남긴다
    resend_api_key: str | None = None
    resend_from: str = "해독 <onboarding@resend.dev>"
    # Gmail 등 SMTP(우선 사용). Gmail은 계정 주소 + 16자리 앱 비밀번호
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_password: str | None = None
    # 안드로이드 TWA 앱 — /.well-known/assetlinks.json 에 실린다. 지문은 쉼표로 여러 개
    android_package: str = "app.vercel.saipr_reading.twa"
    android_cert_sha256: str = (
        "7F:D4:97:F9:FC:B0:1F:F9:A2:CB:2F:1A:A8:BE:65:21:F7:C9:08:3B:34:96:A4:E3:8F:F9:CB:41:7C:35:06:48"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
