"""Parquet storage: per-run staging files plus append-only day files with upsert.

Layout under the data directory:

    <table>/<YYYY-MM-DD>.parquet       day files, the source of truth (committed to git)
    .staging/<run_id>/<table>/*.parquet one file per fetched unit (per item), merged at run end

Every staged file is written atomically (tmp + rename), so a run that dies mid-way
leaves only complete files behind. Merging is an upsert on the table key, keeping
the most recent fetch, so merging the same staged data twice changes nothing.

A refetched row whose values match the stored row (ignoring the bookkeeping columns
`run_id` and `fetched_at`) keeps the stored row, and a day file whose merged content is
unchanged is not rewritten. Each run refetches 7 days of hourly data, so without this
every run would rewrite every day file and git would store a full copy of each.
"""

from __future__ import annotations

import os
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

TS = pa.timestamp("us", tz="UTC")

# Columns that say which run fetched a row, not what was observed.
BOOKKEEPING = ("run_id", "fetched_at")


@dataclass(frozen=True)
class Table:
    name: str
    schema: pa.Schema | None  # None: columns not known in advance (kept as text)
    key: tuple[str, ...]  # upsert key; empty = rows of a staged day replace the day file
    partition: str  # column whose UTC date picks the day file
    order: str | None = "fetched_at"  # newest wins on key conflicts


def _schema(*cols: tuple[str, pa.DataType]) -> pa.Schema:
    return pa.schema([pa.field(n, t) for n, t in cols])


_POINT = (
    ("min", pa.int64()),
    ("p25", pa.int64()),
    ("median", pa.int64()),
    ("p75", pa.int64()),
    ("quantity", pa.int64()),
    ("auctions", pa.int64()),
    ("source", pa.string()),
    ("run_id", pa.string()),
    ("fetched_at", TS),
)

HOURLY = Table(
    "hourly", _schema(("item_id", pa.int64()), ("hour", TS), *_POINT), ("item_id", "hour"), "hour"
)
SCANS = Table(
    "scans",
    _schema(("item_id", pa.int64()), ("observed_at", TS), *_POINT),
    ("item_id", "observed_at"),
    "observed_at",
)
SNAPSHOT = Table(
    "snapshot",
    _schema(
        ("run_id", pa.string()),
        ("scanned_at", TS),
        ("item_id", pa.int64()),
        ("median", pa.int64()),
        ("min_buyout", pa.int64()),
        ("quantity", pa.int64()),
        ("median_7d", pa.int64()),
        ("median_30d", pa.int64()),
        ("low_30d", pa.int64()),
        ("high_30d", pa.int64()),
        ("sales_per_day", pa.float64()),
        ("source", pa.string()),
    ),
    ("scanned_at", "item_id"),
    "scanned_at",
    order=None,
)
ECONOMY = Table(
    "economy",
    _schema(
        ("market", pa.string()),
        ("day", pa.date32()),
        ("kind", pa.string()),
        ("observed_at", TS),
        ("value", pa.int64()),
        ("value_low", pa.int64()),
        ("auctions", pa.int64()),
        ("units", pa.int64()),
        ("items", pa.int64()),
        ("scans", pa.int64()),
        ("contributors", pa.int64()),
        ("source", pa.string()),
        ("run_id", pa.string()),
        ("fetched_at", TS),
    ),
    ("market", "day", "kind"),
    "day",
)
ITEMS = Table(
    "items",
    _schema(
        ("item_id", pa.int64()),
        ("name", pa.string()),
        ("quality", pa.string()),
        ("item_class", pa.string()),
        ("level", pa.int64()),
        ("fetched_at", TS),
        ("source", pa.string()),
        # From /v1/items (null on tooltip rows; the newest row per item wins).
        ("subclass", pa.string()),
        ("required_level", pa.int64()),
        ("vendor_price", pa.int64()),  # copper a vendor pays for one unit (vendorSell)
    ),
    ("item_id",),
    "fetched_at",
)
# One row per recipe and reagent, from /v1/crafting (all=true). No prices: those come
# from the snapshot and hourly tables.
RECIPES = Table(
    "recipes",
    _schema(
        ("spell_id", pa.int64()),
        ("recipe_name", pa.string()),
        ("profession", pa.string()),
        ("skill_required", pa.int64()),
        ("acquisition", pa.string()),
        ("result_id", pa.int64()),
        ("result_name", pa.string()),
        ("result_qty_min", pa.int64()),
        ("result_qty_max", pa.int64()),
        ("reagent_id", pa.int64()),
        ("reagent_name", pa.string()),
        ("reagent_qty", pa.int64()),
        ("source", pa.string()),
        ("run_id", pa.string()),
        ("fetched_at", TS),
    ),
    ("spell_id", "reagent_id"),
    "fetched_at",
)
# Game builds from ahledger.com/feed/builds.xml, one row per feed entry.
BUILDS = Table(
    "builds",
    _schema(
        ("build_id", pa.int64()),
        ("version", pa.string()),
        ("stage", pa.string()),
        ("title", pa.string()),
        ("published_at", TS),
        ("url", pa.string()),
        ("description", pa.string()),
        ("source", pa.string()),
        ("run_id", pa.string()),
        ("fetched_at", TS),
    ),
    ("url",),
    "published_at",
)
WATCHLIST = Table(
    "watchlist",
    _schema(
        ("run_id", pa.string()),
        ("run_started_at", TS),
        ("item_id", pa.int64()),
        ("rank", pa.int64()),
        ("reason", pa.string()),
        ("turnover", pa.float64()),
        ("scans", pa.bool_()),
    ),
    ("run_id", "item_id"),
    "run_started_at",
    order=None,
)
RUNS = Table(
    "runs",
    _schema(
        ("run_id", pa.string()),
        ("started_at", TS),
        ("finished_at", TS),
        ("status", pa.string()),
        ("requests", pa.int64()),
        ("errors", pa.int64()),
        ("retries", pa.int64()),
        ("items_planned", pa.int64()),
        ("hourly_done", pa.int64()),
        ("scans_planned", pa.int64()),
        ("scans_done", pa.int64()),
        ("hourly_rows", pa.int64()),
        ("scan_rows", pa.int64()),
        ("oldest_seen", TS),
        ("newest_seen", TS),
        ("pricetable_scanned_at", TS),
        ("api_archive_until", pa.date32()),
        ("notes", pa.string()),
        ("fetched_at", TS),
    ),
    ("run_id",),
    "started_at",
)
GAPS = Table(
    "gaps",
    _schema(
        ("run_id", pa.string()),
        ("report_at", TS),
        ("item_id", pa.int64()),
        ("window_start", TS),
        ("window_end", TS),
        ("hours_expected", pa.int64()),
        ("hours_present", pa.int64()),
        ("hours_missing", pa.int64()),
        ("longest_gap_hours", pa.int64()),
        ("first_hour", TS),
        ("last_hour", TS),
    ),
    ("run_id", "item_id"),
    "report_at",
    order=None,
)
POPULATION = Table("population", None, (), "fetched_at", order=None)

TABLES = {
    t.name: t
    for t in (
        HOURLY,
        SCANS,
        SNAPSHOT,
        ECONOMY,
        ITEMS,
        WATCHLIST,
        RUNS,
        GAPS,
        POPULATION,
        RECIPES,
        BUILDS,
    )
}


def to_arrow(table: Table, rows: list[dict]) -> pa.Table:
    if table.schema is None:
        cols = list(dict.fromkeys(k for r in rows for k in r))
        fields = [pa.field(c, TS if c == "fetched_at" else pa.string()) for c in cols]
        return pa.Table.from_pylist(rows, schema=pa.schema(fields))
    return pa.Table.from_pylist(rows, schema=table.schema)


def _atomic_write(tbl: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(tbl, tmp, compression="zstd")
    os.replace(tmp, path)


def _day_of(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    # Staging ------------------------------------------------------------------

    def staging_root(self) -> Path:
        return self.data_dir / ".staging"

    def run_dir(self, run_id: str) -> Path:
        return self.staging_root() / run_id

    def staged_path(self, run_id: str, table: Table, name: str) -> Path:
        return self.run_dir(run_id) / table.name / f"{name}.parquet"

    def stage(self, run_id: str, table: Table, name: str, rows: list[dict]) -> Path:
        """Write one unit of fetched rows (may be empty: it then marks the unit as done)."""
        path = self.staged_path(run_id, table, name)
        _atomic_write(to_arrow(table, rows), path)
        return path

    def is_staged(self, run_id: str, table: Table, name: str) -> bool:
        return self.staged_path(run_id, table, name).exists()

    def staged_names(self, run_id: str, table: Table) -> set[str]:
        d = self.run_dir(run_id) / table.name
        return {p.stem for p in d.glob("*.parquet")} if d.exists() else set()

    def read_staged(self, run_id: str, table: Table) -> pa.Table | None:
        d = self.run_dir(run_id) / table.name
        files = sorted(d.glob("*.parquet")) if d.exists() else []
        parts = [pq.read_table(f) for f in files]
        parts = [p for p in parts if p.num_rows]
        if not parts:
            return None
        return pa.concat_tables(parts, promote_options="permissive")

    def staged_runs(self) -> list[str]:
        root = self.staging_root()
        return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []

    def drop_run(self, run_id: str) -> None:
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    # Day files ----------------------------------------------------------------

    def day_path(self, table: Table, day: date) -> Path:
        return self.data_dir / table.name / f"{day.isoformat()}.parquet"

    def day_files(self, table: Table) -> list[Path]:
        d = self.data_dir / table.name
        return sorted(d.glob("*.parquet")) if d.exists() else []

    def upsert(self, table: Table, new: pa.Table) -> list[Path]:
        """Merge rows into their day files. Returns the files written."""
        if new is None or new.num_rows == 0:
            return []
        by_day: dict[date, list[int]] = defaultdict(list)
        for i, v in enumerate(new.column(table.partition).to_pylist()):
            by_day[_day_of(v)].append(i)
        written = []
        for day, idx in sorted(by_day.items()):
            chunk = new.take(pa.array(idx))
            path = self.day_path(table, day)
            old = pq.read_table(path) if path.exists() else None
            merged = self._merge(table, old, chunk)
            if old is not None and merged.equals(old):
                continue  # unchanged: leave the file (and git) alone
            _atomic_write(merged, path)
            written.append(path)
        return written

    def _merge(self, table: Table, old: pa.Table | None, chunk: pa.Table) -> pa.Table:
        if not table.key:  # replace the day's rows
            return chunk
        con = duckdb.connect()
        try:
            con.register("new_rows", chunk)
            if old is not None:
                con.register("old_rows", old)
                new_rows = self._changed_rows_sql(table, old, chunk)
                union = (
                    f"SELECT *, 1 AS _prio FROM ({new_rows}) "
                    "UNION ALL BY NAME SELECT *, 0 AS _prio FROM old_rows"
                )
            else:
                union = "SELECT *, 1 AS _prio FROM new_rows"
            keys = ", ".join(f'"{k}"' for k in table.key)
            order = f'"{table.order}" DESC NULLS LAST, _prio DESC' if table.order else "_prio DESC"
            sql = (
                f"SELECT * EXCLUDE (_prio, _rn) FROM ("
                f"SELECT *, row_number() OVER (PARTITION BY {keys} ORDER BY {order}) AS _rn "
                f"FROM ({union})) WHERE _rn = 1 ORDER BY {keys}"
            )
            result = con.sql(sql).to_arrow_table()
        finally:
            con.close()
        if table.schema is not None:
            result = result.select(table.schema.names).cast(table.schema)
        return result

    @staticmethod
    def _changed_rows_sql(table: Table, old: pa.Table, chunk: pa.Table) -> str:
        """SQL for the new rows that differ from the stored row with the same key.
        A new row identical in every observed column is dropped, so the stored row
        (with its original run_id and fetched_at) survives the merge."""
        new_cols, old_cols = chunk.column_names, set(old.column_names)
        if not set(new_cols) <= old_cols:  # schema grew: keep every new row
            return "SELECT * FROM new_rows"
        on = " AND ".join(f'n."{k}" = o."{k}"' for k in table.key)
        same = [c for c in new_cols if c not in table.key and c not in BOOKKEEPING]
        on += "".join(f' AND n."{c}" IS NOT DISTINCT FROM o."{c}"' for c in same)
        return f"SELECT n.* FROM new_rows n ANTI JOIN old_rows o ON {on}"

    def read_all(self, table: Table) -> pa.Table | None:
        files = self.day_files(table)
        if not files:
            return None
        return pa.concat_tables([pq.read_table(f) for f in files], promote_options="permissive")

    def query(self, sql: str, params: list | None = None, **tables: str) -> pa.Table | None:
        """Run SQL with `{alias}` placeholders bound to read_parquet over a table's day files.
        Returns None when one of the tables has no day files yet."""
        subs = {}
        for alias, tname in tables.items():
            files = [str(p).replace("\\", "/") for p in self.day_files(TABLES[tname])]
            if not files:
                return None
            subs[alias] = (
                "read_parquet([" + ", ".join(f"'{f}'" for f in files) + "], union_by_name=true)"
            )
        con = duckdb.connect()
        try:
            return con.sql(sql.format(**subs), params=params or None).to_arrow_table()
        finally:
            con.close()
