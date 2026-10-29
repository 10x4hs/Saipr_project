import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    "given",
    [
        "postgresql://u:p@ep-x-pooler.neon.tech/db?channel_binding=require&sslmode=require",
        "postgres://u:p@ep-x-pooler.neon.tech/db?sslmode=require&channel_binding=require",
    ],
)
def test_neon_urls_become_asyncpg_safe(given):
    url = Settings(database_url=given).database_url
    assert url == "postgresql+asyncpg://u:p@ep-x-pooler.neon.tech/db?ssl=require"


def test_other_urls_untouched():
    assert Settings(database_url="sqlite+aiosqlite:///x.db").database_url == "sqlite+aiosqlite:///x.db"
