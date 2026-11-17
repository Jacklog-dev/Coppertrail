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
    ECONOMY_COLS,
    HOURLY_COLS,
    ITEM_COLS,
    RECIPE_COLS,
    SCAN_COLS,
    SNAPSHOT_COLS,
)

TZ = "Europe/Berlin"


def make_ctx(
    *,
    hourly: pd.DataFrame | None = None,
    scans: pd.DataFrame | None = None,
    items: pd.DataFrame | None = None,
    snapshot: pd.DataFrame | None = None,
    economy: pd.DataFrame | None = None,
    details: pd.DataFrame | None = None,
    recipes: pd.DataFrame | None = None,
    builds: pd.DataFrame | None = None,
    start: date = date(2026, 11, 1),
    end: date = date(2026, 11, 30),
) -> Context:
    ctx = Context(Path("unused"), None, start, end)
    frames = {
        "hourly": (hourly, HOURLY_COLS),
        "scans": (scans, SCAN_COLS),
        "items": (items, ITEM_COLS),
        "snapshot": (snapshot, SNAPSHOT_COLS),
        "economy": (economy, ECONOMY_COLS),
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


def snapshot_frame(sales: dict[int, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scanned_at": pd.Timestamp("2026-11-16", tz="UTC"),
                "item_id": i,
                "sales_per_day": s,
                "min_buyout": 100,
            }
            for i, s in sales.items()
        ],
        columns=SNAPSHOT_COLS,
    )


def hourly_frame(item_id: int, start: str, values: dict[str, np.ndarray]) -> pd.DataFrame:
    """One row per hour from `start` (UTC); `values` gives min/p25/quantity arrays."""
    n = len(next(iter(values.values())))
    df = pd.DataFrame({"hour": pd.date_range(start, periods=n, freq="h", tz="UTC")})
    df["item_id"] = item_id
    for col in ("min", "p25", "median", "p75", "quantity", "auctions"):
        if col in values:
            df[col] = values[col]
    df["p25"] = df.get("p25", df["min"] * 1.1)
    df["median"] = df.get("median", df["min"] * 1.3)
    df["p75"] = df.get("p75", df["min"] * 1.5)
    df["quantity"] = df.get("quantity", 100)
    df["auctions"] = df.get("auctions", 10)
    df["source"] = "api"
    return df[HOURLY_COLS]


def scans_frame(
    item_id: int, start: str, minutes: int, values: dict[str, np.ndarray]
) -> pd.DataFrame:
    n = len(next(iter(values.values())))
    df = pd.DataFrame(
        {"observed_at": pd.date_range(start, periods=n, freq=f"{minutes}min", tz="UTC")}
    )
    df["item_id"] = item_id
    for col, v in values.items():
        df[col] = v
    df["p25"] = df.get("p25", df["min"] * 1.1)
    df["median"] = df.get("median", df["min"] * 1.3)
    df["p75"] = df.get("p75", df["min"] * 1.5)
    df["quantity"] = df.get("quantity", 100)
    df["auctions"] = df.get("auctions", 10)
    df["source"] = "api"
    return df[SCAN_COLS]


def local_hours(start: str, n: int) -> np.ndarray:
    """CET hour of day for n hourly UTC steps from `start`."""
    return pd.date_range(start, periods=n, freq="h", tz="UTC").tz_convert(TZ).hour.to_numpy()


def noise(n: int, seed: int, scale: float = 0.02) -> np.ndarray:
    return 1 + np.random.default_rng(seed).normal(0, scale, n)
