"""Synthetic inputs for pattern job tests: a Context whose frames are preset."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context
from coppertrail.query.series import (
    BUILD_COLS,
    DETAIL_COLS,
    HOURLY_COLS,
    HOUSE_COLS,
    ITEM_COLS,
    LATEST_COLS,
    RECIPE_COLS,
)

TZ = "Europe/Berlin"


def make_ctx(
    *,
    hourly: pd.DataFrame | None = None,
    items: pd.DataFrame | None = None,
    latest: pd.DataFrame | None = None,
    house: pd.DataFrame | None = None,
    details: pd.DataFrame | None = None,
    recipes: pd.DataFrame | None = None,
    builds: pd.DataFrame | None = None,
    start: date = date(2026, 11, 1),
    end: date = date(2026, 11, 30),
) -> Context:
    ctx = Context(Path("unused"), None, start, end)
    frames = {
        "hourly": (hourly, HOURLY_COLS),
        "items": (items, ITEM_COLS),
        "latest": (latest, LATEST_COLS),
        "house": (house, HOUSE_COLS),
        "details": (details, DETAIL_COLS),
        "recipes": (recipes, RECIPE_COLS),
        "builds": (builds, BUILD_COLS),
    }
    for key, (df, cols) in frames.items():
        ctx.__dict__[key] = pd.DataFrame(columns=cols) if df is None else df
    ctx.__dict__["span"] = (start, end)
    return ctx


def items_frame(rows: list[tuple[int, str, int]], item_class: str = "Trade Goods") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"item_id": i, "name": n, "item_class": item_class, "quality": "COMMON", "level": lv}
            for i, n, lv in rows
        ],
        columns=ITEM_COLS,
    )


def latest_frame(sales: dict[int, float], min_buyout: float = 100) -> pd.DataFrame:
    """`latest_per_item` rows: sales/day per item, every lowest buyout `min_buyout`."""
    return pd.DataFrame(
        [
            {
                "item_id": i,
                "observed_at": pd.Timestamp("2026-11-16", tz="UTC"),
                "sales_per_day": s,
                "min_buyout": min_buyout,
            }
            for i, s in sales.items()
        ],
        columns=LATEST_COLS,
    )


def hourly_frame(
    item_id: int, start: str, values: dict[str, np.ndarray], jitter_s: np.ndarray | None = None
) -> pd.DataFrame:
    """One row per hour (snapshot) from `start` (UTC); `values` gives min/p25/quantity/...
    arrays. `observed_at` is 22 minutes past the hour, plus `jitter_s` seconds."""
    n = len(next(iter(values.values())))
    df = pd.DataFrame({"hour": pd.date_range(start, periods=n, freq="h", tz="UTC")})
    df["observed_at"] = df["hour"] + pd.Timedelta(minutes=22)
    if jitter_s is not None:
        df["observed_at"] += pd.to_timedelta(jitter_s, unit="s")
    df["item_id"] = item_id
    for col, v in values.items():
        df[col] = v
    df["p25"] = df.get("p25", df["min"] * 1.1)
    df["median"] = df.get("median", df["min"] * 1.3)
    df["p75"] = df.get("p75", df["min"] * 1.5)
    df["quantity"] = df.get("quantity", 100)
    df["auctions"] = df.get("auctions", 10)
    df["source"] = "blizzard"
    return df.reindex(columns=HOURLY_COLS)


def local_hours(start: str, n: int) -> np.ndarray:
    """CET hour of day for n hourly UTC steps from `start`."""
    return pd.date_range(start, periods=n, freq="h", tz="UTC").tz_convert(TZ).hour.to_numpy()


def noise(n: int, seed: int, scale: float = 0.02) -> np.ndarray:
    return 1 + np.random.default_rng(seed).normal(0, scale, n)
