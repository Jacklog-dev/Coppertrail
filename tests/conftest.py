from datetime import UTC, datetime, timedelta

import pytest

from coppertrail.collector.legacy.store import TABLES, Store, to_arrow

ITEMS = [
    # item_id, name, class, min_buyout (copper), sales/day
    (2318, "Light Leather", "Trade Goods", 35, 25_000.0),
    (8170, "Rugged Leather", "Trade Goods", 1_495, 9_221.0),
    (15407, "Cured Rugged Hide", "Trade Goods", 233_098, 40.0),
    (15564, "Rugged Armor Kit", "Trade Goods", 12_500, 8.0),
    (2447, "Peacebloom", "Trade Goods", 52, 12_760.0),
    (13468, "Black Lotus", "Trade Goods", 2_500_000, 12.0),
    (12359, "Thorium Bar", "Trade Goods", 6_000, 3_000.0),
    (3928, "Superior Healing Potion", "Consumable", 4_000, 300.0),
    (4407, "Accurate Scope", "Consumable", 4_030, 112.3),
]


@pytest.fixture
def archive(tmp_path):
    """A small data folder: items, two snapshots (the newer one wins), hourly 9-16 Nov."""
    data = tmp_path / "data"
    store = Store(data)
    t0 = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
    store.upsert(
        TABLES["items"],
        to_arrow(
            TABLES["items"],
            [
                {
                    "item_id": i,
                    "name": n,
                    "quality": "COMMON",
                    "item_class": c,
                    "level": 1,
                    "fetched_at": t0,
                    "source": "api",
                }
                for i, n, c, _, _ in ITEMS
            ],
        ),
    )
    snaps = []
    for age, factor in ((timedelta(hours=6), 2), (timedelta(0), 1)):
        snaps += [
            {
                "run_id": "r",
                "scanned_at": t0 - age,
                "item_id": i,
                "median": p,
                "min_buyout": p * factor,
                "quantity": 10,
                "median_7d": p,
                "median_30d": p,
                "low_30d": p,
                "high_30d": p,
                "sales_per_day": s,
                "source": "api",
            }
            for i, _, _, p, s in ITEMS
        ]
    store.upsert(TABLES["snapshot"], to_arrow(TABLES["snapshot"], snaps))
    hours = [datetime(2026, 11, 9, tzinfo=UTC) + timedelta(hours=h) for h in range(8 * 24)]
    store.upsert(
        TABLES["hourly"],
        to_arrow(
            TABLES["hourly"],
            [
                {
                    "item_id": 2318,
                    "hour": h,
                    "min": 30,
                    "p25": 32,
                    "median": 40,
                    "p75": 50,
                    "quantity": 100,
                    "auctions": 5,
                    "source": "api",
                    "run_id": "r",
                    "fetched_at": t0,
                }
                for h in hours
            ],
        ),
    )
    return data


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    d = tmp_path / "config"
    monkeypatch.setenv("COPPERTRAIL_CONFIG", str(d))
    return d
