from datetime import UTC, date, datetime

import pytest

from coppertrail.ui import format as fmt


@pytest.mark.parametrize(
    ("copper", "parts", "text"),
    [
        (126_705, [(12, "g"), (67, "s"), (5, "c")], "12g 67s 5c"),
        (1_908, [(19, "s"), (8, "c")], "19s 8c"),
        (480_000, [(48, "g")], "48g"),
        (15_000, [(1, "g"), (50, "s")], "1g 50s"),
        (8_000, [(80, "s")], "80s"),
        (0, [(0, "c")], "0c"),
        (999_999, [(99, "g"), (99, "s"), (99, "c")], "99g 99s 99c"),
        (1_000_000, [(100, "g")], "100g"),  # short form from 100 gold
        (31_010_000, [(3_101, "g")], "3,101g"),
        (31_015_000, [(3_102, "g")], "3,102g"),  # short form rounds
    ],
)
def test_coins(copper, parts, text):
    assert fmt.coin_parts(copper) == parts
    assert fmt.coins_text(copper) == text


def test_coins_reject_negative():
    with pytest.raises(ValueError):
        fmt.coin_parts(-1)


@pytest.mark.parametrize(
    ("pct", "text", "direction"),
    [
        (14.23, "▲ +14.2 %", "rise"),
        (-87.4, "▼ −87 %", "fall"),  # no decimal from 50 % on
        (-3.25, "▼ −3.2 %", "fall"),
        (488.0, "▲ +488 %", "rise"),
        (1_234.0, "▲ +1,234 %", "rise"),
        (0.0, "± 0.0 %", "flat"),
        (0.04, "± 0.0 %", "flat"),  # rounds to zero: no arrow
        (-0.04, "± 0.0 %", "flat"),
        (49.96, "▲ +50.0 %", "rise"),
    ],
)
def test_percent_change(pct, text, direction):
    assert fmt.percent_change(pct) == (text, direction)


def test_percent_uses_real_minus_not_hyphen():
    text, _ = fmt.percent_change(-12.0)
    assert "-" not in text
    assert fmt.MINUS in text


@pytest.mark.parametrize(
    ("n", "text"),
    [
        (9_063, "9,063"),
        (412, "412"),
        (999_999, "999,999"),
        (1_610_000, "1.61 M"),
        (12_500_000, "12.5 M"),
    ],
)
def test_count(n, text):
    assert fmt.count(n) == text


def test_dates_in_local_time_and_english_months():
    # 07:42 UTC is 08:42 CET in November.
    assert fmt.local_datetime(datetime(2026, 11, 16, 7, 42, tzinfo=UTC)) == "16 Nov 2026, 08:42"
    assert fmt.local_datetime(datetime(2026, 11, 16, 7, 42)) == "16 Nov 2026, 08:42"
    assert fmt.day(date(2026, 11, 9)) == "9 Nov 2026"
    assert fmt.date_range(date(2026, 10, 17), date(2026, 11, 16)) == "17 Oct – 16 Nov 2026"
    assert fmt.date_range(date(2025, 12, 30), date(2026, 1, 2)) == ("30 Dec 2025 – 2 Jan 2026")
