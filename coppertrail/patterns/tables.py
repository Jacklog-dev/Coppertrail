"""Readers for the tables the query layer does not cover yet: recipes, builds, item details.

They live here (not in `coppertrail.query`) because the query layer belongs to another
session; move them to `query/series.py` when it adds them. Each returns a typed empty
frame when the table has no day files yet (the collector fills `recipes`, `builds` and
the item detail columns from its 2026-11-18 run on).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from coppertrail.collector.store import TABLES, Store

RECIPE_COLS = [
    "spell_id",
    "recipe_name",
    "profession",
    "skill_required",
    "result_id",
    "result_name",
    "result_qty_min",
    "result_qty_max",
    "reagent_id",
    "reagent_name",
    "reagent_qty",
]
BUILD_COLS = ["build_id", "version", "stage", "title", "published_at", "url"]
DETAIL_COLS = ["item_id", "subclass", "required_level", "vendor_price"]


def _empty(table: str, cols: list[str]) -> pd.DataFrame:
    return TABLES[table].schema.empty_table().select(cols).to_pandas()


def _bounds(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    lo = datetime.combine(start, time(), UTC) if start else None
    hi = datetime.combine(end + timedelta(days=1), time(), UTC) if end else None
    return lo, hi


def recipes(data_dir: Path) -> pd.DataFrame:
    """One row per recipe and reagent, from the newest fetch of each (spell, reagent)."""
    store = Store(data_dir)
    tbl = store.query(
        f"SELECT {', '.join(RECIPE_COLS)} FROM (SELECT *, row_number() OVER "
        "(PARTITION BY spell_id, reagent_id ORDER BY fetched_at DESC) rn FROM {r}) "
        "WHERE rn = 1 ORDER BY spell_id, reagent_id",
        r="recipes",
    )
    return tbl.to_pandas() if tbl is not None else _empty("recipes", RECIPE_COLS)


def builds(data_dir: Path, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Game builds, one row per feed entry, `published_at` (UTC) inside the day range."""
    store = Store(data_dir)
    lo, hi = _bounds(start, end)
    where, params = [], []
    if lo is not None:
        where.append("published_at >= ?")
        params.append(lo)
    if hi is not None:
        where.append("published_at < ?")
        params.append(hi)
    sql = (
        f"SELECT {', '.join(BUILD_COLS)} FROM (SELECT *, row_number() OVER "
        "(PARTITION BY url ORDER BY fetched_at DESC) rn FROM {b}) WHERE rn = 1"
    )
    if where:
        sql += " AND " + " AND ".join(where)
    tbl = store.query(sql + " ORDER BY published_at", params or None, b="builds")
    if tbl is None:
        return _empty("builds", BUILD_COLS)
    df = tbl.to_pandas()
    # Store.query leaves the DuckDB session in local time; the query layer's rule is UTC.
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
    return df


def item_details(data_dir: Path) -> pd.DataFrame:
    """Per item the newest non-null subclass, required level and vendor price.

    Tooltip rows carry nulls in these columns, so the newest row alone is not enough.
    Items without any detail row are left out.
    """
    store = Store(data_dir)
    try:
        tbl = store.query(
            "SELECT item_id, "
            "arg_max(subclass, fetched_at) FILTER (WHERE subclass IS NOT NULL) AS subclass, "
            "arg_max(required_level, fetched_at) FILTER (WHERE required_level IS NOT NULL) "
            "AS required_level, "
            "arg_max(vendor_price, fetched_at) FILTER (WHERE vendor_price IS NOT NULL) "
            "AS vendor_price "
            "FROM {i} GROUP BY item_id HAVING count(vendor_price) + count(subclass) "
            "+ count(required_level) > 0 ORDER BY item_id",
            i="items",
        )
    except duckdb.BinderException:  # only day files from before the detail columns existed
        tbl = None
    if tbl is None:
        return _empty("items", DETAIL_COLS)
    return tbl.to_pandas()
