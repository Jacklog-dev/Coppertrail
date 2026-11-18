"""Parquet storage for the Blizzard collector.

Two folders:
- `data_dir` (the data repo's `main` checkout): Coppertrail's own conclusions, kept for good.
  `hourly/` and `house/` are one write-once file per snapshot
  (`<name>/<YYYY-MM-DD>/<HH>.parquet`); `selection/` and `builds/` are day files.
  Rows a source fed carry a `source` column (`blizzard`), the tables themselves are
  source-neutral, so another source can feed them later.
- `window_dir` (`<data>/window/`, not in git; moved as a GitHub Actions artifact): data
  copied unchanged from a source, at most `copied_days` old, as day files under the
  source's own folder (`<source>/<name>/<YYYY-MM-DD>.parquet`, today `blizzard/items/`,
  `blizzard/recipes/`).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

TS = pa.timestamp("us", tz="UTC")


@dataclass(frozen=True)
class Table:
    name: str
    branch: str  # "main" (data_dir, in git) or "window" (window_dir, not in git)
    layout: str  # "hour" or "day"
    schema: pa.Schema
    required: frozenset[str]
    partition: str  # column whose UTC time picks the file
    sort: tuple[str, ...] = ()
    source: str | None = None  # set for data copied from a source; None for our own


def _table(name, branch, layout, partition, cols, required=(), sort=(), source=None):
    schema = pa.schema([pa.field(n, t, nullable=n not in required) for n, t in cols])
    return Table(name, branch, layout, schema, frozenset(required), partition, tuple(sort), source)


HOURLY = _table(
    "hourly",
    "main",
    "hour",
    "observed_at",
    [
        ("item_id", pa.int32()),
        ("hour", TS),
        ("observed_at", TS),
        ("min", pa.int64()),
        ("p25", pa.int64()),
        ("median", pa.int64()),
        ("p75", pa.int64()),
        ("quantity", pa.int32()),
        ("auctions", pa.int32()),
        ("gone_units", pa.int32()),
        ("partial_units", pa.int32()),
        ("short_gone_units", pa.int32()),
        ("new_units", pa.int32()),
        ("span_hours", pa.float32()),
        ("source", pa.string()),
    ],
    required=("item_id", "hour", "observed_at", "quantity", "auctions", "source"),
    sort=("item_id",),
)
HOUSE = _table(
    "house",
    "main",
    "hour",
    "observed_at",
    [
        ("hour", TS),
        ("observed_at", TS),
        ("auctions", pa.int32()),
        ("units", pa.int64()),
        ("gold_listed", pa.int64()),
        ("gone_auctions", pa.int32()),
        ("new_auctions", pa.int32()),
        ("sold_value_est", pa.int64()),
        ("source", pa.string()),
    ],
    required=("hour", "observed_at", "source"),
)
SELECTION = _table(
    "selection",
    "main",
    "day",
    "day",
    [("day", pa.date32()), ("item_id", pa.int32()), ("reason", pa.string()), ("rank", pa.int32())],
    required=("day", "item_id", "reason"),
    sort=("item_id",),
)
BUILDS = _table(
    "builds",
    "main",
    "day",
    "first_seen",
    [
        ("version", pa.string()),
        ("build", pa.int32()),
        ("namespace", pa.string()),
        ("first_seen", TS),
        ("source", pa.string()),
    ],
    required=("namespace", "first_seen", "source"),
)
ITEMS = _table(
    "items",
    "window",
    "day",
    "fetched_at",
    [
        ("item_id", pa.int32()),
        ("found", pa.bool_()),
        ("name", pa.string()),
        ("quality", pa.string()),
        ("class_id", pa.int16()),
        ("class", pa.string()),
        ("subclass_id", pa.int16()),
        ("subclass", pa.string()),
        ("required_level", pa.int16()),
        ("sell_price", pa.int64()),
        ("purchase_price", pa.int64()),
        ("item_level", pa.int16()),
        ("namespace", pa.string()),
        ("fetched_at", TS),
    ],
    required=("item_id", "found", "fetched_at"),
    sort=("item_id",),
    source="blizzard",
)
RECIPES = _table(
    "recipes",
    "window",
    "day",
    "fetched_at",
    [
        ("recipe_id", pa.int32()),
        ("name", pa.string()),
        ("profession", pa.string()),
        ("crafted_item_id", pa.int32()),
        ("crafted_qty", pa.float32()),
        ("reagent_id", pa.int32()),
        ("reagent_qty", pa.int16()),
        ("fetched_at", TS),
    ],
    required=("recipe_id", "fetched_at"),
    sort=("recipe_id",),
    source="blizzard",
)

TABLES: dict[str, Table] = {t.name: t for t in (HOURLY, HOUSE, SELECTION, BUILDS, ITEMS, RECIPES)}


def to_table(table: Table, df: pd.DataFrame) -> pa.Table:
    """The frame in the table's schema: unknown columns and missing required ones are errors,
    missing nullable columns become nulls."""
    names = table.schema.names
    extra = sorted(set(df.columns) - set(names))
    if extra:
        raise ValueError(f"{table.name}: unknown column(s) {', '.join(extra)}")
    missing = sorted(table.required - set(df.columns))
    if missing:
        raise ValueError(f"{table.name}: missing column(s) {', '.join(missing)}")
    df = df.copy()
    for col in names:
        if col not in df.columns:
            df[col] = None
    if table.sort:
        df = df.sort_values(list(table.sort), kind="stable")
    return pa.Table.from_pandas(df[names], schema=table.schema, preserve_index=False)


def _atomic_write(tbl: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(tbl, tmp, compression="zstd", compression_level=9)
    os.replace(tmp, path)


def _day(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


class Store:
    def __init__(self, data_dir: Path, window_dir: Path):
        self.data_dir = Path(data_dir)
        self.window_dir = Path(window_dir)

    def root(self, table: Table) -> Path:
        if table.branch == "main":
            return self.data_dir / table.name
        return self.window_dir / table.source / table.name

    def path(self, table: Table, when: datetime | date) -> Path:
        day = _day(when).isoformat()
        if table.layout == "hour":
            if not isinstance(when, datetime):
                raise TypeError(f"{table.name} needs a datetime, got {when!r}")
            return self.root(table) / day / f"{when.hour:02d}.parquet"
        return self.root(table) / f"{day}.parquet"

    def write_hour(self, table: Table, observed_at: datetime, df: pd.DataFrame) -> Path | None:
        """Write one snapshot's file. Hour files are written once: an existing file for
        that hour is left untouched and None is returned."""
        tbl = to_table(table, df)
        path = self.path(table, observed_at)
        if path.exists():
            have = pq.read_table(path, columns=["observed_at"]).column(0)
            if len(have) and have[0].as_py() != observed_at:
                log.warning("%s: %s already holds another snapshot, kept", table.name, path)
            return None
        _atomic_write(tbl, path)
        return path

    def write_day(self, table: Table, day: date, df: pd.DataFrame) -> Path:
        path = self.path(table, day)
        _atomic_write(to_table(table, df), path)
        return path

    def files(self, table: Table, start: date | None = None, end: date | None = None) -> list[Path]:
        root = self.root(table)
        if not root.exists():
            return []

        def in_range(name: str) -> bool:
            try:
                d = date.fromisoformat(name)
            except ValueError:
                return False
            return (start is None or d >= start) and (end is None or d <= end)

        if table.layout == "hour":
            days = sorted(p for p in root.iterdir() if p.is_dir() and in_range(p.name))
            return [f for d in days for f in sorted(d.glob("*.parquet"))]
        return sorted(p for p in root.glob("*.parquet") if in_range(p.stem))

    def read(
        self, table: Table, start: date | None = None, end: date | None = None
    ) -> pa.Table | None:
        files = self.files(table, start, end)
        if not files:
            return None
        return pa.concat_tables(pq.read_table(f, schema=table.schema) for f in files)
