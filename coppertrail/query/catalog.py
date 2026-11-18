"""Item catalog and archive status for the filter bar and status strip."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from coppertrail.collector.store import HOURLY
from coppertrail.query import series

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
    min_buyout: int | None  # copper, from the newest hour
    sales_per_day: float  # 0.0 when the item has no sales estimate


STALE_AFTER = timedelta(hours=3)  # one snapshot an hour; three missed ones make it stale
MISSING_WINDOW_H = 7 * 24


@dataclass(frozen=True)
class ArchiveStatus:
    first_hour: datetime | None  # first snapshot hour in `hourly/` (UTC)
    last_hour: datetime | None  # newest snapshot hour (UTC)
    hours: int = 0  # snapshot hours stored
    missing_hours_7d: int = 0  # hours without a snapshot in the 7 days up to last_hour
    stale: bool = False  # last_hour older than 3 h when the status was read
    as_of: datetime | None = None  # the newest snapshot's observed_at (else last_hour)

    def __post_init__(self):
        if self.as_of is None and self.last_hour is not None:
            object.__setattr__(self, "as_of", self.last_hour)

    @property
    def empty(self) -> bool:
        return self.last_hour is None

    @property
    def first_day(self) -> date | None:
        return None if self.first_hour is None else self.first_hour.date()

    @property
    def last_day(self) -> date | None:
        return None if self.last_hour is None else self.last_hour.date()

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


def load_items(data_dir: Path) -> list[Item]:
    """Every known item (details or selection), with lowest buyout and sales/day from
    the newest hour. Items Blizzard has no name for show as `#<id>`."""
    it = series.items(data_dir)
    if it.empty:
        return []
    latest = series.latest_per_item(data_dir).set_index("item_id")
    out = []
    for r in it.itertuples(index=False):
        mb = latest["min_buyout"].get(r.item_id) if len(latest) else None
        spd = latest["sales_per_day"].get(r.item_id) if len(latest) else None
        out.append(
            Item(
                item_id=int(r.item_id),
                name=r.name,
                item_class=r.item_class if isinstance(r.item_class, str) else "",
                quality=r.quality if isinstance(r.quality, str) else "",
                min_buyout=None if mb is None or mb != mb else int(mb),
                sales_per_day=0.0 if spd is None or spd != spd else float(spd),
            )
        )
    return sorted(out, key=lambda i: (i.name.casefold(), i.item_id))


def _hour_of(path: Path) -> datetime | None:
    try:
        day = date.fromisoformat(path.parent.name)
        return datetime(day.year, day.month, day.day, int(path.stem), tzinfo=UTC)
    except ValueError:
        return None


def archive_status(data_dir: Path, now: datetime | None = None) -> ArchiveStatus:
    """From the hour file names (one per snapshot); only the newest file is opened."""
    files = series.store_of(data_dir).files(HOURLY)
    hours = sorted({h for h in map(_hour_of, files) if h is not None})
    if not hours:
        return ArchiveStatus(None, None)
    first, last = hours[0], hours[-1]
    since = last - timedelta(hours=MISSING_WINDOW_H - 1)
    expected = int((last - max(first, since)) / timedelta(hours=1)) + 1
    have = sum(1 for h in hours if h >= since)
    as_of = None
    try:
        col = pq.read_table(files[-1], columns=["observed_at"]).column(0)
        as_of = max((v.as_py() for v in col if v.is_valid), default=None)
    except (OSError, ValueError):
        pass
    now = now or datetime.now(UTC)
    return ArchiveStatus(
        first_hour=first,
        last_hour=last,
        hours=len(hours),
        missing_hours_7d=expected - have,
        stale=now - last > STALE_AFTER,
        as_of=as_of,
    )
