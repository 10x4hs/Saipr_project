from app.core.config import get_settings
from app.services import books as book_service
from app.services.pace import (
    DWELL_CAP_MULTIPLIER,
    PAGE_DWELL_MS,
    credited_dwell_ms,
    is_verified,
    min_dwell_ms,
)


def test_every_page_takes_flat_15s():
    assert PAGE_DWELL_MS == 15_000
    assert min_dwell_ms("가" * 300, "ko") == 15_000
    assert min_dwell_ms("a" * 600, "en") == 15_000


def test_length_and_language_do_not_matter():
    assert min_dwell_ms("가" * 3000, "ko") == min_dwell_ms("가", "ko") == min_dwell_ms("") == 15_000
    assert min_dwell_ms("word " * 2000) == 15_000


def test_dwell_scale_still_multiplies(monkeypatch):
    monkeypatch.setattr(get_settings(), "dwell_scale", 0.2)
    assert book_service.required_dwell_ms("가" * 900, "ko") == 3_000
    monkeypatch.setattr(get_settings(), "dwell_scale", 1.0)
    assert book_service.required_dwell_ms("가" * 900, "ko") == 15_000


def test_skimming_is_not_verified():
    need = min_dwell_ms("가" * 1200, "ko")
    assert not is_verified(need - 1, need)
    assert is_verified(need, need)


def test_idle_tab_dwell_is_capped():
    assert credited_dwell_ms(10**9, 1000) == 1000 * DWELL_CAP_MULTIPLIER
    assert credited_dwell_ms(-5, 1000) == 0
