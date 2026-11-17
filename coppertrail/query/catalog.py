"""Item catalog and archive status for the filter bar and status strip."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from coppertrail.collector.store import TABLES, Store

DEFAULT_DATA_DIR = Path("private")


def default_data_dir() -> Path:
    """`$COPPERTRAIL_DATA`, else `./private` (same rule as the collector CLI).

    The frozen Windows build has no meaningful working directory (a double-click starts it
    wherever), so there `./private` means the `private` folder next to the .exe. A missing
    folder just shows the empty state; the folder picker in the app chooses a real one.
    """
    if env := os.environ.get("COPPERTRAIL_DATA"):
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / DEFAULT_DATA_DIR
    return DEFAULT_DATA_DIR


@dataclass(frozen=True)
class Item:
    item_id: int
    name: str
    item_class: str
    quality: str
    min_buyout: int | None  # copper, from the latest snapshot
    sales_per_day: float  # 0.0 when the item has no snapshot row


@dataclass(frozen=True)
class ArchiveStatus:
    as_of: datetime | None  # newest price scan in the archive (UTC)
    first_day: date | None  # first day with hourly data
    last_day: date | None  # last day with hourly data

    @property
    def empty(self) -> bool:
        return self.as_of is None

    @property
    def days(self) -> int:
        if self.first_day is None or self.last_day is None:
            return 0
        return (self.last_day - self.first_day).days + 1

    def age_days(self, now: datetime | None = None) -> float | None:
        if self.as_of is None:
            return None
        now = now or datetime.now(UTC)
        return (now - self.as_of).total_seconds() / 86_400


def _utc(epoch: float | None) -> datetime | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, UTC)


def load_items(data_dir: Path) -> list[Item]:
    """Every named item, with lowest buyout and sales/day from its latest snapshot row."""
    store = Store(data_dir)
    if not store.day_files(TABLES["items"]):
        return []
    if store.day_files(TABLES["snapshot"]):
        sql = """
            WITH latest AS (
                SELECT item_id, min_buyout, sales_per_day,
                       row_number() OVER (PARTITION BY item_id ORDER BY scanned_at DESC) AS rn
                FROM {snapshot}
            ), names AS (
                SELECT item_id, name, item_class, quality,
                       row_number() OVER (PARTITION BY item_id ORDER BY fetched_at DESC) AS rn
                FROM {items}
            )
            SELECT n.item_id, n.name, n.item_class, n.quality, l.min_buyout, l.sales_per_day
            FROM names n LEFT JOIN latest l ON l.item_id = n.item_id AND l.rn = 1
            WHERE n.rn = 1 AND n.name IS NOT NULL
            ORDER BY n.name
        """
        tbl = store.query(sql, items="items", snapshot="snapshot")
    else:
        sql = """
            SELECT item_id, name, item_class, quality, NULL AS min_buyout, NULL AS sales_per_day
            FROM (SELECT *, row_number() OVER (PARTITION BY item_id ORDER BY fetched_at DESC) rn
                  FROM {items}) WHERE rn = 1 AND name IS NOT NULL ORDER BY name
        """
        tbl = store.query(sql, items="items")
    if tbl is None:
        return []
    return [
        Item(
            item_id=int(r["item_id"]),
            name=r["name"],
            item_class=r["item_class"] or "",
            quality=r["quality"] or "",
            min_buyout=None if r["min_buyout"] is None else int(r["min_buyout"]),
            sales_per_day=float(r["sales_per_day"] or 0.0),
        )
        for r in tbl.to_pylist()
    ]


def archive_status(data_dir: Path) -> ArchiveStatus:
    store = Store(data_dir)
    as_of = first = last = None
    # epoch() keeps DuckDB from converting TIMESTAMPTZ values in Python (needs pytz).
    if store.day_files(TABLES["snapshot"]):
        tbl = store.query("SELECT max(epoch(scanned_at)) AS t FROM {s}", s="snapshot")
        as_of = _utc(tbl.column("t")[0].as_py()) if tbl is not None else None
    if store.day_files(TABLES["hourly"]):
        tbl = store.query(
            "SELECT min(epoch(hour)) AS a, max(epoch(hour)) AS b FROM {h}", h="hourly"
        )
        if tbl is not None:
            a, b = tbl.column("a")[0].as_py(), tbl.column("b")[0].as_py()
            first = _utc(a).date() if a is not None else None
            last = _utc(b).date() if b is not None else None
            if as_of is None and b is not None:
                as_of = _utc(b)
    return ArchiveStatus(as_of=as_of, first_day=first, last_day=last)
