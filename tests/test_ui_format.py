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


def test_short_datetime_and_clock():
    ts = datetime(2026, 11, 13, 6, 55, 4, tzinfo=UTC)  # 07:55 CET
    assert fmt.short_datetime(ts) == "13 Nov, 07:55"
    assert fmt.clock(ts) == "07:55:04"


@pytest.mark.parametrize(
    ("days", "text"),
    [
        (1, "Needs 1 more day of data"),
        (5, "Needs 5 more days of data"),
        (13, "Needs 13 more days of data"),
        (14, "Needs 2 more weeks of data"),
        (15, "Needs 3 more weeks of data"),  # rounds up: never promise too early
        (21, "Needs 3 more weeks of data"),
    ],
)
def test_needs_more(days, text):
    assert fmt.needs_more(days) == text


def test_view_helpers():
    ts = datetime(2026, 11, 16, 5, 10, tzinfo=UTC)  # 06:10 CET
    assert fmt.day_month(date(2026, 11, 7)) == "7 Nov"
    assert fmt.hour_of_day(7) == "07:00"
    assert fmt.points(19.84) == "+19.8 pts"
    assert fmt.points(-27.0) == "−27.0 pts"
    assert fmt.share(0.163) == "16.3 %"
    assert fmt.short_datetime(ts) == "16 Nov, 06:10"


def test_change_from_fraction():
    assert fmt.change(-0.87) == {"text": "▼ −87 %", "dir": "fall"}
    assert fmt.change(0.142) == {"text": "▲ +14.2 %", "dir": "rise"}
    assert fmt.change(None) is None
    assert fmt.change(float("nan")) is None
    assert fmt.signed_percent(-0.041) == "−4.1 %"


def test_pattern_helpers():
    assert fmt.minutes(30.4) == "30 min"
    assert fmt.minutes(108) == "1 h 48 min"
    assert fmt.minutes(120) == "2 h"
    assert fmt.ratio(1.0712) == "1.07 ×"
    assert fmt.whole_share(0.833) == "83 %"
    assert fmt.signed_coins_text(-14_050) == "−1g 40s 50c"
