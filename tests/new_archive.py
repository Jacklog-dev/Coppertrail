"""Hand-made data folders in the Blizzard layout (main checkout plus `window/`).

`make_archive(tmp_path, items, hours)` writes every table through `Store`:
- `items`: tuples `(item_id, name, class[, quality, subclass, required_level, sell_price,
  item_level])`, one `ITEMS` row each (window), plus a `SELECTION` day file of these ids.
- `hours`: item id -> list of `HOURLY` row dicts. `hour` is required; `observed_at`
  defaults to `hour + 22 min`, `quantity`/`auctions` to 10/1, `source` to "blizzard".
  One hour file per hour, and one `HOUSE` row per hour summed from the item rows.
- `recipes`: `RECIPES` row dicts (window); `builds`: `BUILDS` row dicts (main).
- `house`: explicit `HOUSE` row dicts (`hour` required, `observed_at` = hour + 22 min),
  written instead of the summed ones.
No real auction data: every value here is invented.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from coppertrail.collector.store import BUILDS, HOURLY, HOUSE, ITEMS, RECIPES, SELECTION, Store

FETCHED = datetime(2026, 11, 16, 6, 0, tzinfo=UTC)
ITEM_FIELDS = (
    "item_id",
    "name",
    "class",
    "quality",
    "subclass",
    "required_level",
    "sell_price",
    "item_level",
)


def hours_from(start: datetime, n: int, **row) -> list[dict]:
    """`n` consecutive hourly rows from `start`, each with the given fields."""
    return [{"hour": start + timedelta(hours=h), **row} for h in range(n)]


def item_row(t: tuple, fetched_at: datetime = FETCHED) -> dict:
    row = dict(zip(ITEM_FIELDS, t, strict=False))
    row.setdefault("quality", "COMMON")
    return {**row, "found": True, "namespace": "static-forever-eu", "fetched_at": fetched_at}


def make_archive(
    tmp_path: Path,
    items: list[tuple],
    hours: dict[int, list[dict]],
    *,
    recipes: list[dict] | None = None,
    builds: list[dict] | None = None,
    house: list[dict] | None = None,
) -> Path:
    data = Path(tmp_path) / "data"
    store = Store(data, data / "window")
    if items:
        store.write_day(ITEMS, FETCHED.date(), pd.DataFrame([item_row(t) for t in items]))
        sel = pd.DataFrame(
            {"day": FETCHED.date(), "item_id": [t[0] for t in items], "reason": "rule"}
        )
        store.write_day(SELECTION, FETCHED.date(), sel)
    by_hour: dict[datetime, list[dict]] = defaultdict(list)
    for item_id, rows in hours.items():
        for r in rows:
            row = {"quantity": 10, "auctions": 1, "source": "blizzard", **r, "item_id": item_id}
            row.setdefault("observed_at", row["hour"] + timedelta(minutes=22))
            by_hour[row["hour"]].append(row)
    for hour, rows in sorted(by_hour.items()):
        df = pd.DataFrame(rows)
        observed = df["observed_at"].iloc[0]
        df["observed_at"] = observed  # one snapshot per hour
        store.write_hour(HOURLY, observed, df)
        price = df["min"] if "min" in df else pd.Series(0, index=df.index)
        summed = {
            "hour": hour,
            "observed_at": observed,
            "auctions": int(df["auctions"].sum()),
            "units": int(df["quantity"].sum()),
            "gold_listed": int((price.fillna(0) * df["quantity"]).sum()),
            "source": "blizzard",
        }
        if house is None:
            store.write_hour(HOUSE, observed, pd.DataFrame([summed]))
    for r in house or []:
        row = {"observed_at": r["hour"] + timedelta(minutes=22), "source": "blizzard", **r}
        store.write_hour(HOUSE, row["observed_at"], pd.DataFrame([row]))
    if recipes:
        rec = pd.DataFrame([{"fetched_at": FETCHED, **r} for r in recipes])
        store.write_day(RECIPES, FETCHED.date(), rec)
    if builds:
        b = pd.DataFrame([{"source": "blizzard", **r} for r in builds])
        for day, g in b.groupby(b["first_seen"].map(lambda t: t.date())):
            store.write_day(BUILDS, day, g)
    return data


# The shared sample archive (the `archive` fixture in conftest.py).

SAMPLE_ITEMS = [
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


def sample_day_rows(price: int, sales: int) -> list[dict]:
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


def sample_hours() -> dict[int, list[dict]]:
    """Every sample item with the last 24 snapshots up to 16 Nov 07:00 UTC (lowest buyout
    and sales/day as in SAMPLE_ITEMS), and Light Leather hourly from 9 Nov 00:00 on."""
    hours = {i: sample_day_rows(p, s) for i, _, _, p, s in SAMPLE_ITEMS}
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
    return hours
