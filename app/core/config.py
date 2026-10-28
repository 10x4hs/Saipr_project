from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "saipr"
    database_url: str = "postgresql+asyncpg://saipr:saipr@localhost:5432/saipr"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
