from datetime import UTC, datetime, timedelta

import pytest

from tests.new_archive import make_archive

ITEMS = [
    # item_id, name, class, min_buyout (copper), sales/day
    (2318, "Light Leather", "Trade Goods", 35, 25_000),
    (8170, "Rugged Leather", "Trade Goods", 1_495, 9_221),
    (15407, "Cured Rugged Hide", "Trade Goods", 233_098, 40),
    (15564, "Rugged Armor Kit", "Trade Goods", 12_500, 8),
    (2447, "Peacebloom", "Trade Goods", 52, 12_760),
    (13468, "Black Lotus", "Trade Goods", 2_500_000, 12),
    (12359, "Thorium Bar", "Trade Goods", 6_000, 3_000),
    (3928, "Superior Healing Potion", "Consumable", 4_000, 300),
    (4407, "Accurate Scope", "Consumable", 4_030, 112),
]
LAST_HOUR = datetime(2026, 11, 16, 7, tzinfo=UTC)  # the archive's newest snapshot
FIRST_HOUR = datetime(2026, 11, 9, tzinfo=UTC)
HOURS_2318 = int((LAST_HOUR - FIRST_HOUR) / timedelta(hours=1)) + 1  # 176


def _day_rows(price: int, sales: int) -> list[dict]:
    """The last 24 snapshots: lowest buyout `price`, `sales` units gone over the day."""
    start = LAST_HOUR - timedelta(hours=23)
    rows = []
    for h in range(24):
        gone = sales // 24 + (sales % 24 if h == 0 else 0)
        hour = start + timedelta(hours=h)
        rows.append(
            {
                "hour": hour,
                "observed_at": hour,
                "min": price,
                "p25": price,
                "median": price,
                "p75": price,
                "gone_units": gone,
                "partial_units": 0,
                "span_hours": 1.0,
            }
        )
    return rows


@pytest.fixture
def archive(tmp_path):
    """A small data folder: 9 items, each with the last 24 snapshots up to 16 Nov 07:00 UTC
    (lowest buyout and sales/day as in ITEMS), and Light Leather hourly from 9 Nov on."""
    hours = {i: _day_rows(p, s) for i, _, _, p, s in ITEMS}
    early = [
        {
            "hour": FIRST_HOUR + timedelta(hours=h),
            "observed_at": FIRST_HOUR + timedelta(hours=h),
            "min": 30,
            "p25": 32,
            "median": 40,
            "p75": 50,
            "quantity": 100,
            "auctions": 5,
        }
        for h in range(HOURS_2318 - 24)
    ]
    hours[2318] = early + hours[2318]
    return make_archive(tmp_path, [(i, n, c) for i, n, c, _, _ in ITEMS], hours)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    d = tmp_path / "config"
    monkeypatch.setenv("COPPERTRAIL_CONFIG", str(d))
    return d
