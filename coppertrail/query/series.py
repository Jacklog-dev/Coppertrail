"""Time series from the day files, as pandas frames for pattern jobs and charts.

Every reader takes an optional item id list and an inclusive (start, end) day range
in UTC, the same days `filtering.date_window` resolves. Only the day files inside
the range are read. Timestamps come back timezone-aware in UTC; convert for display.
Missing tables or an empty range give an empty frame with the expected columns.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from coppertrail.collector.store import TABLES, Store, Table

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
