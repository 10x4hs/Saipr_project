from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "saipr"
    # 기본은 파일 SQLite — Docker 없이 `uvicorn` 한 줄로 실행. Compose에서는 Postgres URL을 주입한다.
    database_url: str = "sqlite+aiosqlite:///./saipr.db"
    # 연결 풀을 끈다. 테스트처럼 여러 이벤트 루프가 같은 엔진을 쓸 때 필요하다(SQLite는 항상 꺼짐).
    db_disable_pool: bool = False

    # 세션 쿠키 서명 키. 운영에서는 반드시 환경변수로 바꾼다.
    secret_key: str = "dev-only-change-me"
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 14 * 24 * 3600
    # OAuth 콜백 URL을 만들 때 쓰는 외부 주소
    public_base_url: str = "http://localhost:8000"

    # 외부 소스별 타임아웃. 한 소스가 느려도 통합 검색 전체가 막히지 않도록 짧게 둔다.
    http_timeout_seconds: float = 3.0

    # 키가 비어 있는 소스는 자동 비활성화된다 (registry.build_sources 참고).
    kakao_rest_api_key: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    google_books_api_key: str | None = None
    wikisource_lang: str = "ko"

    # 소셜 로그인. 키가 비어 있는 제공자는 로그인 화면에 버튼이 나오지 않는다 (services/oauth.py).
    # 카카오는 도서 검색용 REST 키를 로그인 client_id로도 쓴다.
    kakao_client_secret: str | None = None
    kakao_login_enabled: bool = False
    google_client_id: str | None = None
    google_client_secret: str | None = None
    naver_login_enabled: bool = False

    # 웹 푸시(VAPID). 키를 비워 두면 처음 실행할 때 vapid_key_file에 만들어 저장한다 (커밋 금지).
    vapid_private_key: str | None = None
    vapid_key_file: str = "./.vapid_private.pem"
    # 푸시 서비스가 연락처로 보는 값. py_vapid는 mailto:만 받고,
    # 애플은 localhost 메일을 거부하므로 실제 도메인을 쓴다.
    vapid_subject: str = "mailto:saipr-demo@users.noreply.github.com"

    # 배틀 정산·주간 리셋 같은 주기 작업 (services/scheduler.py). 테스트에서는 끈다.
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 60

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, url: str) -> str:
        """Render·Fly 같은 호스팅이 주는 postgres:// 주소를 asyncpg 드라이버 주소로 바꾼다."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix) :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
