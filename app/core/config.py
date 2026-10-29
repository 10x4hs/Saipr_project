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


@lru_cache
def get_settings() -> Settings:
    return Settings()
