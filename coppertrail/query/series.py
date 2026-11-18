"""Time series from the data folder, as pandas frames for pattern jobs and charts.

The data folder is the data repo's `main` checkout (`hourly/`, `house/`, `selection/`,
`builds/`, kept for good) with the `window` checkout in `<data>/window/` (`blizzard/items/`,
`blizzard/recipes/`, copied from Blizzard, at most 30 days old).

Every reader takes an optional item id list and an inclusive (start, end) day range
in UTC, the same days `filtering.date_window` resolves. Only the files of days inside
the range are read. Timestamps come back timezone-aware in UTC; convert for display.
Missing tables or an empty range give an empty frame with the expected columns.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa

from coppertrail.collector.store import (
    BUILDS,
    HOURLY,
    HOUSE,
    ITEMS,
    RECIPES,
    SELECTION,
    Store,
    Table,
)

HOURLY_COLS = HOURLY.schema.names
HOUSE_COLS = HOUSE.schema.names
ITEM_COLS = [
    "item_id",
    "name",
    "quality",
    "item_class",
    "subclass",
    "required_level",
    "vendor_price",
    "level",
]
DETAIL_COLS = ["item_id", "subclass", "required_level", "vendor_price"]
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
BUILD_COLS = ["build_id", "version", "stage", "title", "published_at", "namespace"]
LATEST_COLS = [
    "item_id",
    "observed_at",
    "median",
    "min_buyout",
    "quantity",
    "median_7d",
    "median_30d",
    "low_30d",
    "high_30d",
    "sales_per_day",
]
LATEST_DAYS = 30  # latest_per_item looks at the last 30 days of hourly rows
SALES_DAYS = 7  # sales_per_day averages over the last 7 days

_TS = pa.timestamp("us", tz="UTC")
_TYPES = {
    "item_id": pa.int32(),
    "name": pa.string(),
    "quality": pa.string(),
    "item_class": pa.string(),
    "subclass": pa.string(),
    "required_level": pa.int16(),
    "vendor_price": pa.int64(),
    "level": pa.int16(),
    "spell_id": pa.int32(),
    "recipe_name": pa.string(),
    "profession": pa.string(),
    "skill_required": pa.int16(),
    "result_id": pa.int32(),
    "result_name": pa.string(),
    "result_qty_min": pa.float32(),
    "result_qty_max": pa.float32(),
    "reagent_id": pa.int32(),
    "reagent_name": pa.string(),
    "reagent_qty": pa.int16(),
    "build_id": pa.int32(),
    "version": pa.string(),
    "stage": pa.string(),
    "title": pa.string(),
    "published_at": _TS,
    "namespace": pa.string(),
    "observed_at": _TS,
    "median": pa.int64(),
    "min_buyout": pa.int64(),
    "quantity": pa.int32(),
    "median_7d": pa.float64(),
    "median_30d": pa.float64(),
    "low_30d": pa.int64(),
    "high_30d": pa.int64(),
    "sales_per_day": pa.float64(),
}


def store_of(data_dir: Path) -> Store:
    """The main checkout and its `window/` checkout."""
    data_dir = Path(data_dir)
    return Store(data_dir, data_dir / "window")


def _empty_cols(cols: list[str]) -> pd.DataFrame:
    return pa.schema([(c, _TYPES[c]) for c in cols]).empty_table().to_pandas()


def _empty(t: Table, cols: list[str] | None = None) -> pd.DataFrame:
    return t.schema.empty_table().select(cols or t.schema.names).to_pandas()


def _src(files: list[Path]) -> str:
    paths = ", ".join("'" + str(f).replace("\\", "/").replace("'", "''") + "'" for f in files)
    return f"read_parquet([{paths}], union_by_name=true)"


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")  # else TIMESTAMPTZ comes back in local time
    return con


def _query(sql: str, params: list | None = None) -> pd.DataFrame:
    con = _connect()
    try:
        return con.sql(sql, params=params or None).to_arrow_table().to_pandas()
    finally:
        con.close()


def _bounds(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    lo = datetime.combine(start, time(), UTC) if start else None
    hi = datetime.combine(end + timedelta(days=1), time(), UTC) if end else None
    return lo, hi


def _ids(item_ids: Iterable[int] | None) -> list[int] | None:
    return None if item_ids is None else sorted({int(i) for i in item_ids})


def _hour_rows(
    data_dir: Path,
    t: Table,
    item_ids: Iterable[int] | None,
    start: date | None,
    end: date | None,
    order: str,
) -> pd.DataFrame:
    ids = _ids(item_ids)
    files = store_of(data_dir).files(t, start, end)
    if not files or ids == []:
        return _empty(t)
    where, params = [], []
    if ids is not None:
        where.append("item_id IN (SELECT unnest(?::BIGINT[]))")
        params.append(ids)
    lo, hi = _bounds(start, end)
    if lo is not None:
        where.append("hour >= ?")
        params.append(lo)
    if hi is not None:
        where.append("hour < ?")
        params.append(hi)
    cols = ", ".join(f'"{c}"' for c in t.schema.names)
    sql = f"SELECT {cols} FROM {_src(files)}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    con = _connect()
    try:
        tbl = con.sql(sql + f" ORDER BY {order}", params=params or None).to_arrow_table()
    finally:
        con.close()
    return tbl.cast(t.schema).to_pandas()


def hourly(
    data_dir: Path,
    item_ids: Iterable[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """One row per (item_id, hour) and snapshot: copper per unit, quantity, sales estimate."""
    return _hour_rows(data_dir, HOURLY, item_ids, start, end, "item_id, hour")


def house(data_dir: Path, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """One row per snapshot for the whole house (`gold_listed` in copper, `units`, ...)."""
    return _hour_rows(data_dir, HOUSE, None, start, end, "hour")


def _newest_items_sql(files: list[Path]) -> str:
    return (
        f"SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY item_id "
        f"ORDER BY fetched_at DESC) rn FROM {_src(files)}) WHERE rn = 1"
    )


def items(data_dir: Path) -> pd.DataFrame:
    """Item details, the newest row per item. Items without a name (unknown to Blizzard,
    or only in the newest selection) get the name `#<id>`."""
    store = store_of(data_dir)
    item_files = store.files(ITEMS)
    sel_files = store.files(SELECTION)[-1:]
    if not item_files and not sel_files:
        return _empty_cols(ITEM_COLS)
    parts = []
    if item_files:
        parts.append(
            'SELECT item_id, name, quality, "class" AS item_class, subclass, required_level, '
            "sell_price AS vendor_price, item_level AS level "
            f"FROM ({_newest_items_sql(item_files)})"
        )
    if sel_files:
        known = f"SELECT item_id FROM {_src(item_files)}" if item_files else "SELECT NULL"
        parts.append(
            "SELECT DISTINCT item_id, NULL, NULL, NULL, NULL, NULL, NULL, NULL "
            f"FROM {_src(sel_files)} WHERE item_id NOT IN ({known})"
        )
    df = _query(
        "SELECT item_id, coalesce(name, '#' || item_id) AS name, quality, item_class, subclass, "
        f"required_level, vendor_price, level FROM ({' UNION ALL '.join(parts)}) ORDER BY item_id"
    )
    tbl = pa.Table.from_pandas(df, preserve_index=False)
    return tbl.cast(pa.schema([(c, _TYPES[c]) for c in ITEM_COLS])).to_pandas()


def item_details(data_dir: Path) -> pd.DataFrame:
    """Per item the newest non-null subclass, required level and vendor price.
    Items without any of them are left out."""
    files = store_of(data_dir).files(ITEMS)
    if not files:
        return _empty_cols(DETAIL_COLS)
    return _query(
        "SELECT item_id, "
        "arg_max(subclass, fetched_at) FILTER (WHERE subclass IS NOT NULL) AS subclass, "
        "arg_max(required_level, fetched_at) FILTER (WHERE required_level IS NOT NULL) "
        "AS required_level, "
        "arg_max(sell_price, fetched_at) FILTER (WHERE sell_price IS NOT NULL) AS vendor_price "
        f"FROM {_src(files)} GROUP BY item_id HAVING count(sell_price) + count(subclass) "
        "+ count(required_level) > 0 ORDER BY item_id"
    )


def recipes(data_dir: Path) -> pd.DataFrame:
    """One row per recipe and reagent, from the newest fetch of each (recipe, reagent).
    Names of the crafted item and the reagents come from the item details."""
    store = store_of(data_dir)
    files = store.files(RECIPES)
    if not files:
        return _empty_cols(RECIPE_COLS)
    item_files = store.files(ITEMS)
    names = (
        f"SELECT item_id, name FROM ({_newest_items_sql(item_files)})"
        if item_files
        else "SELECT NULL::INTEGER AS item_id, NULL::VARCHAR AS name WHERE false"
    )
    df = _query(
        "WITH r AS (SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY recipe_id, "
        f"reagent_id ORDER BY fetched_at DESC) rn FROM {_src(files)}) WHERE rn = 1), "
        f"n AS ({names}) "
        "SELECT r.recipe_id AS spell_id, r.name AS recipe_name, r.profession, "
        "NULL AS skill_required, r.crafted_item_id AS result_id, cn.name AS result_name, "
        "r.crafted_qty AS result_qty_min, r.crafted_qty AS result_qty_max, r.reagent_id, "
        "rn_.name AS reagent_name, r.reagent_qty "
        "FROM r LEFT JOIN n cn ON cn.item_id = r.crafted_item_id "
        "LEFT JOIN n rn_ ON rn_.item_id = r.reagent_id ORDER BY spell_id, reagent_id"
    )
    tbl = pa.Table.from_pandas(df, preserve_index=False)
    return tbl.cast(pa.schema([(c, _TYPES[c]) for c in RECIPE_COLS])).to_pandas()


def builds(data_dir: Path, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Game builds, one row per namespace, `published_at` = when it was first seen (UTC),
    inside the day range."""
    files = store_of(data_dir).files(BUILDS)
    if not files:
        return _empty_cols(BUILD_COLS)
    where, params = [], []
    lo, hi = _bounds(start, end)
    if lo is not None:
        where.append("published_at >= ?")
        params.append(lo)
    if hi is not None:
        where.append("published_at < ?")
        params.append(hi)
    sql = (
        "SELECT build AS build_id, any_value(version) AS version, '' AS stage, "
        "namespace AS title, min(first_seen) AS published_at, namespace "
        f"FROM {_src(files)} GROUP BY namespace, build"
    )
    sql = f"SELECT * FROM ({sql})"
    if where:
        sql += " WHERE " + " AND ".join(where)
    df = _query(sql + " ORDER BY published_at", params)
    tbl = pa.Table.from_pandas(df, preserve_index=False)
    return tbl.cast(pa.schema([(c, _TYPES[c]) for c in BUILD_COLS])).to_pandas()


def latest_per_item(data_dir: Path, item_ids: Iterable[int] | None = None) -> pd.DataFrame:
    """Per item the newest hour (median, lowest buyout, quantity) with 7- and 30-day medians
    of the hourly medians, the 30-day low and high of the hourly lowest buyout, and
    sales/day: the sales estimate (`gone_units + partial_units`) of the last 7 days over
    the days the estimate covers (the house's `span_hours`, summed per snapshot, / 24;
    NULL when none is covered). Windows end at the archive's newest hour."""
    ids = _ids(item_ids)
    store = store_of(data_dir)
    every = store.files(HOURLY)
    if not every or ids == []:
        return _empty_cols(LATEST_COLS)
    last_day = date.fromisoformat(every[-1].parent.name)
    files = store.files(HOURLY, last_day - timedelta(days=LATEST_DAYS))
    pick = "WHERE item_id IN (SELECT unnest(?::BIGINT[]))" if ids is not None else ""
    src = _src(files)
    sql = f"""
        WITH ref AS (SELECT max(hour) AS t FROM {src}),
        h AS (
            SELECT h.* FROM {src} h, ref
            WHERE h.hour > ref.t - INTERVAL {LATEST_DAYS} DAY
        ),
        cover AS (
            SELECT sum(span) / 24.0 AS days FROM (
                SELECT max(span_hours) AS span FROM h, ref
                WHERE h.hour > ref.t - INTERVAL {SALES_DAYS} DAY GROUP BY h.hour)
        ),
        sel AS (SELECT * FROM h {pick}),
        stats AS (
            SELECT item_id,
                arg_max(observed_at, hour) AS observed_at,
                arg_max(median, hour) AS median,
                arg_max("min", hour) AS min_buyout,
                arg_max(quantity, hour) AS quantity,
                median(median) FILTER (WHERE hour > (SELECT t FROM ref) - INTERVAL {SALES_DAYS} DAY)
                    AS median_7d,
                median(median) AS median_30d,
                min("min") AS low_30d,
                max("min") AS high_30d,
                sum(coalesce(gone_units, 0) + coalesce(partial_units, 0))
                    FILTER (WHERE hour > (SELECT t FROM ref) - INTERVAL {SALES_DAYS} DAY
                            AND span_hours IS NOT NULL) AS sold
            FROM sel GROUP BY item_id
        )
        SELECT item_id, observed_at, median, min_buyout, quantity, median_7d, median_30d,
            low_30d, high_30d,
            CASE WHEN cover.days > 0 THEN coalesce(sold, 0) / cover.days END AS sales_per_day
        FROM stats, cover ORDER BY item_id
    """
    df = _query(sql, [ids] if ids is not None else None)
    tbl = pa.Table.from_pandas(df, preserve_index=False)
    return tbl.cast(pa.schema([(c, _TYPES[c]) for c in LATEST_COLS])).to_pandas()
