"""Hand-made data folders in the Blizzard layout (main checkout plus `window/`).

`make_archive(tmp_path, items, hours)` writes every table through `Store`:
- `items`: tuples `(item_id, name, class[, quality, subclass, required_level, sell_price,
  item_level])`, one `ITEMS` row each (window), plus a `SELECTION` day file of these ids.
- `hours`: item id -> list of `HOURLY` row dicts. `hour` is required; `observed_at`
  defaults to `hour + 22 min`, `quantity`/`auctions` to 10/1, `source` to "blizzard".
  One hour file per hour, and one `HOUSE` row per hour summed from the item rows.
- `recipes`: `RECIPES` row dicts (window); `builds`: `BUILDS` row dicts (main).
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
        house = {
            "hour": hour,
            "observed_at": observed,
            "auctions": int(df["auctions"].sum()),
            "units": int(df["quantity"].sum()),
            "gold_listed": int((price.fillna(0) * df["quantity"]).sum()),
        }
        store.write_hour(HOUSE, observed, pd.DataFrame([house]))
    if recipes:
        rec = pd.DataFrame([{"fetched_at": FETCHED, **r} for r in recipes])
        store.write_day(RECIPES, FETCHED.date(), rec)
    if builds:
        b = pd.DataFrame(builds)
        for day, g in b.groupby(b["first_seen"].map(lambda t: t.date())):
            store.write_day(BUILDS, day, g)
    return data
