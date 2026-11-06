from app.services.pace import (
    DWELL_CAP_MULTIPLIER,
    MIN_DWELL_MS,
    PAGE_DWELL_MS,
    credited_dwell_ms,
    is_verified,
    min_dwell_ms,
)


def test_one_baseline_page_takes_30s():
    assert min_dwell_ms("가" * 300, "ko") == PAGE_DWELL_MS
    assert min_dwell_ms("a" * 600, "en") == PAGE_DWELL_MS


def test_required_time_scales_with_chars():
    assert min_dwell_ms("가" * 900, "ko") == 3 * PAGE_DWELL_MS
    assert min_dwell_ms("가" * 450, "ko") == 45_000


def test_whitespace_is_not_counted():
    assert min_dwell_ms("가 " * 600, "ko") == min_dwell_ms("가" * 600, "ko")
    assert min_dwell_ms("가\n\n" * 600, "ko") == 60_000


def test_short_chunk_has_a_floor():
    assert min_dwell_ms("가", "ko") == MIN_DWELL_MS
    assert min_dwell_ms("", "ko") == MIN_DWELL_MS


def test_language_autodetect():
    assert min_dwell_ms("가" * 600) == 60_000
    assert min_dwell_ms("word " * 300) == 60_000  # 1200글자 / 600


def test_skimming_is_not_verified():
    need = min_dwell_ms("가" * 1200, "ko")
    assert not is_verified(need - 1, need)
    assert is_verified(need, need)


def test_idle_tab_dwell_is_capped():
    assert credited_dwell_ms(10**9, 1000) == 1000 * DWELL_CAP_MULTIPLIER
    assert credited_dwell_ms(-5, 1000) == 0
