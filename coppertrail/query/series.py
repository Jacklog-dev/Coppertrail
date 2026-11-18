"""Time series from the day files, as pandas frames for pattern jobs and charts.

Every reader takes an optional item id list and an inclusive (start, end) day range
in UTC, the same days `filtering.date_window` resolves. Only the day files inside
the range are read. Timestamps come back timezone-aware in UTC; convert for display.
Missing tables or an empty range give an empty frame with the expected columns.
Also: recipes, game builds and item details (subclass, required level, vendor price).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from coppertrail.collector.legacy.store import TABLES, Store, Table

HOURLY_COLS = ["item_id", "hour", "min", "p25", "median", "p75", "quantity", "auctions", "source"]
SCAN_COLS = [
    "item_id",
    "observed_at",
    "min",
    "p25",
    "median",
    "p75",
    "quantity",
    "auctions",
    "source",
]
SNAPSHOT_COLS = [
    "scanned_at",
    "item_id",
    "median",
    "min_buyout",
    "quantity",
    "median_7d",
    "median_30d",
    "low_30d",
    "high_30d",
    "sales_per_day",
    "source",
]
ECONOMY_COLS = ["day", "kind", "value", "value_low", "auctions", "units", "scans", "source"]
ITEM_COLS = ["item_id", "name", "item_class", "quality", "level"]


def _files(store: Store, table: Table, start: date | None, end: date | None) -> list[str]:
    out = []
    for p in store.day_files(table):
        try:
            day = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if (start is None or day >= start) and (end is None or day <= end):
            out.append(str(p).replace("\\", "/"))
    return out


def _bounds(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    lo = datetime.combine(start, time(), UTC) if start else None
    hi = datetime.combine(end + timedelta(days=1), time(), UTC) if end else None
    return lo, hi


def _read(
    data_dir: Path,
    table: str,
    cols: list[str],
    ts_col: str,
    item_ids: Iterable[int] | None,
    start: date | None,
    end: date | None,
    order: str,
) -> pd.DataFrame:
    store = Store(data_dir)
    t = TABLES[table]
    ids = None if item_ids is None else sorted({int(i) for i in item_ids})
    files = _files(store, t, start, end)
    if not files or ids == []:
        return _empty(t, cols)
    src = "read_parquet([" + ", ".join(f"'{f}'" for f in files) + "], union_by_name=true)"
    where, params = [], []
    if ids is not None:
        where.append("item_id IN (SELECT unnest(?::BIGINT[]))")
        params.append(ids)
    lo, hi = _bounds(start, end)
    if lo is not None:
        where.append(f'"{ts_col}" >= ?')
        params.append(lo)
    if hi is not None:
        where.append(f'"{ts_col}" < ?')
        params.append(hi)
    sql = f"SELECT {', '.join(f'"{c}"' for c in cols)} FROM {src}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order}"
    con = _connect()
    try:
        tbl = con.sql(sql, params=params or None).to_arrow_table()
    finally:
        con.close()
    return tbl.to_pandas()


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")  # else TIMESTAMPTZ comes back in local time
    return con


def _empty(t: Table, cols: list[str]) -> pd.DataFrame:
    if t.schema is None:
        return pd.DataFrame(columns=cols)
    return t.schema.empty_table().select(cols).to_pandas()


def hourly(
    data_dir: Path,
    item_ids: Iterable[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Hourly buckets: one row per (item_id, hour), prices in copper."""
    return _read(data_dir, "hourly", HOURLY_COLS, "hour", item_ids, start, end, "item_id, hour")


def scans(
    data_dir: Path,
    item_ids: Iterable[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Per-scan points (top items by turnover only): one row per (item_id, observed_at)."""
    return _read(
        data_dir, "scans", SCAN_COLS, "observed_at", item_ids, start, end, "item_id, observed_at"
    )


def snapshots(
    data_dir: Path,
    item_ids: Iterable[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Price table snapshots, one row per (scanned_at, item_id)."""
    return _read(
        data_dir,
        "snapshot",
        SNAPSHOT_COLS,
        "scanned_at",
        item_ids,
        start,
        end,
        "scanned_at, item_id",
    )


def latest_snapshot(data_dir: Path, item_ids: Iterable[int] | None = None) -> pd.DataFrame:
    """The newest snapshot row per item (lowest buyout, sales/day, medians)."""
    snaps = snapshots(data_dir, item_ids)
    if snaps.empty:
        return snaps
    return snaps.sort_values("scanned_at").groupby("item_id", as_index=False).tail(1)


def economy(
    data_dir: Path, start: date | None = None, end: date | None = None, kind: str = "daily"
) -> pd.DataFrame:
    """Market totals per day (`value` = gold listed in copper, `auctions`, `units`)."""
    store = Store(data_dir)
    t = TABLES["economy"]
    files = [str(p).replace("\\", "/") for p in store.day_files(t)]
    if not files:
        return _empty(t, ECONOMY_COLS)
    src = "read_parquet([" + ", ".join(f"'{f}'" for f in files) + "], union_by_name=true)"
    where, params = ["kind = ?"], [kind]
    if start:
        where.append("day >= ?")
        params.append(start)
    if end:
        where.append("day <= ?")
        params.append(end)
    sql = f"SELECT {', '.join(ECONOMY_COLS)} FROM {src} WHERE {' AND '.join(where)} ORDER BY day"
    con = _connect()
    try:
        return con.sql(sql, params=params).to_arrow_table().to_pandas()
    finally:
        con.close()


def items(data_dir: Path) -> pd.DataFrame:
    """Master data, the newest row per item: name, class, quality, level."""
    store = Store(data_dir)
    if not store.day_files(TABLES["items"]):
        return _empty(TABLES["items"], ITEM_COLS)
    tbl = store.query(
        f"SELECT {', '.join(ITEM_COLS)} FROM (SELECT *, row_number() OVER "
        "(PARTITION BY item_id ORDER BY fetched_at DESC) rn FROM {i}) WHERE rn = 1 "
        "ORDER BY item_id",
        i="items",
    )
    return tbl.to_pandas() if tbl is not None else _empty(TABLES["items"], ITEM_COLS)


# Recipes, builds and item details (written by the collector since 2026-11-17).

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


def recipes(data_dir: Path) -> pd.DataFrame:
    """One row per recipe and reagent, from the newest fetch of each (spell, reagent)."""
    store = Store(data_dir)
    tbl = store.query(
        f"SELECT {', '.join(RECIPE_COLS)} FROM (SELECT *, row_number() OVER "
        "(PARTITION BY spell_id, reagent_id ORDER BY fetched_at DESC) rn FROM {r}) "
        "WHERE rn = 1 ORDER BY spell_id, reagent_id",
        r="recipes",
    )
    return tbl.to_pandas() if tbl is not None else _empty(TABLES["recipes"], RECIPE_COLS)


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
        return _empty(TABLES["builds"], BUILD_COLS)
    df = tbl.to_pandas()
    # Store.query leaves the DuckDB session in local time; this layer returns UTC.
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
        return _empty(TABLES["items"], DETAIL_COLS)
    return tbl.to_pandas()
