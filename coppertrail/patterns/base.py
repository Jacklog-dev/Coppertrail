"""The contract every pattern job follows (HANDOVER section 6).

A pattern job is a plain function `fn(ctx) -> PatternResult`, registered with the
`@pattern(...)` decorator. It reads data only through `Context` (which wraps
`coppertrail.query.series`), returns pandas frames, and never touches widget code,
so it is testable and callable from the CLI. `run()` fills the basis fields (days of
data, date range) and refuses to compute when the archive is shorter than the
pattern's `min_days`: the result then says how many days are missing and when the
pattern will be ready, which the GUI shows as the "too little history" state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from functools import cached_property
from pathlib import Path

import pandas as pd

from coppertrail.query import series
from coppertrail.query.catalog import archive_status

# Shared by patterns 3, 4 and 5 so the GUI's event markers, the Item detail events
# table and "What changed" read one shape. `at` is a UTC timestamp, `magnitude` a
# signed fraction (-0.42 = 42 % below the reference) used for ranking and colour.
EVENT_COLS = ["item_id", "at", "type", "detail", "magnitude"]
EVENT_TYPES = ("mispricing", "supply_shock", "buyout")

DATA_KINDS = ("hourly", "scans", "snapshot", "economy", "items", "recipes", "builds")


def events_frame(rows: Iterable[dict] | None = None) -> pd.DataFrame:
    df = pd.DataFrame(list(rows or []), columns=EVENT_COLS)
    df["item_id"] = df["item_id"].astype("int64")
    df["at"] = pd.to_datetime(df["at"], utc=True)
    df["magnitude"] = df["magnitude"].astype("float64")
    bad = set(df["type"]) - set(EVENT_TYPES)
    if bad:
        raise ValueError(f"unknown event types: {sorted(bad)}")
    return df


@dataclass
class Context:
    """What a pattern job may read: one item selection and one inclusive UTC day range."""

    data_dir: Path
    item_ids: list[int] | None
    start: date
    end: date

    @cached_property
    def hourly(self) -> pd.DataFrame:
        return series.hourly(self.data_dir, self.item_ids, self.start, self.end)

    @cached_property
    def scans(self) -> pd.DataFrame:
        return series.scans(self.data_dir, self.item_ids, self.start, self.end)

    @cached_property
    def snapshot(self) -> pd.DataFrame:
        """Latest snapshot row per selected item (not limited to the date range)."""
        return series.latest_snapshot(self.data_dir, self.item_ids)

    @cached_property
    def economy(self) -> pd.DataFrame:
        return series.economy(self.data_dir, self.start, self.end)

    @cached_property
    def items(self) -> pd.DataFrame:
        it = series.items(self.data_dir)
        if self.item_ids is not None:
            it = it[it["item_id"].isin(self.item_ids)]
        return it.reset_index(drop=True)

    @cached_property
    def details(self) -> pd.DataFrame:
        """subclass, required_level, vendor_price per selected item (items with details only)."""
        d = series.item_details(self.data_dir)
        if self.item_ids is not None:
            d = d[d["item_id"].isin(self.item_ids)]
        return d.reset_index(drop=True)

    @cached_property
    def recipes(self) -> pd.DataFrame:
        """All recipes (one row per reagent), not limited by the item selection."""
        return series.recipes(self.data_dir)

    @cached_property
    def builds(self) -> pd.DataFrame:
        """Builds published inside the day range."""
        return series.builds(self.data_dir, self.start, self.end)

    def hourly_of(self, item_ids: Iterable[int]) -> pd.DataFrame:
        """Hourly rows for these items in the range, even outside the selection.

        For jobs that need prices of related items (recipe reagents, products).
        """
        ids = sorted({int(i) for i in item_ids})
        if self.item_ids is None:
            return self.hourly[self.hourly["item_id"].isin(ids)].reset_index(drop=True)
        return series.hourly(self.data_dir, ids, self.start, self.end)

    def snapshot_of(self, item_ids: Iterable[int]) -> pd.DataFrame:
        """Latest snapshot row for these items, even outside the selection."""
        ids = sorted({int(i) for i in item_ids})
        if self.item_ids is None:
            return self.snapshot[self.snapshot["item_id"].isin(ids)].reset_index(drop=True)
        return series.latest_snapshot(self.data_dir, ids)

    @cached_property
    def span(self) -> tuple[date | None, date | None]:
        """First and last day inside the range that the archive actually covers."""
        st = archive_status(self.data_dir)
        if st.first_day is None or st.last_day is None:
            return None, None
        lo, hi = max(self.start, st.first_day), min(self.end, st.last_day)
        return (lo, hi) if lo <= hi else (None, None)

    @property
    def days(self) -> int:
        lo, hi = self.span
        return 0 if lo is None or hi is None else (hi - lo).days + 1


@dataclass
class PatternResult:
    """Everything a pattern view needs. Jobs set the data fields; `run()` the basis."""

    ranked: pd.DataFrame = field(default_factory=pd.DataFrame)  # one row per item, best first
    charts: dict[str, pd.DataFrame] = field(default_factory=dict)
    events: pd.DataFrame | None = None  # EVENT_COLS, for patterns that find events
    items_checked: int = 0
    items_hit: int = 0
    note: str = ""  # extra method detail from the job, appended to the spec's note
    # Filled by run():
    key: str = ""
    title: str = ""
    method: str = ""
    days_used: int = 0
    first_day: date | None = None
    last_day: date | None = None
    needs_days: int = 0  # > 0: too little history, nothing was computed
    ready_on: date | None = None

    @property
    def ready(self) -> bool:
        return self.needs_days == 0

    def basis_line(self) -> str:
        if not self.ready:
            return (
                f"Needs {self.needs_days} more days of data "
                f"(ready around {self.ready_on.isoformat() if self.ready_on else '?'})"
            )
        span = (
            f" ({self.first_day.isoformat()} to {self.last_day.isoformat()})"
            if self.first_day and self.last_day
            else ""
        )
        return (
            f"Rests on {self.days_used} days of data{span} · {self.items_checked} items checked"
            f" · {self.items_hit} items show the pattern"
        )


@dataclass(frozen=True)
class PatternSpec:
    key: str
    number: int  # HANDOVER section 6 number
    title: str
    min_days: int
    data: tuple[str, ...]
    method: str
    fn: Callable[[Context], PatternResult]


REGISTRY: dict[str, PatternSpec] = {}


def pattern(
    key: str, *, number: int, title: str, min_days: int, data: tuple[str, ...], method: str
) -> Callable[[Callable[[Context], PatternResult]], Callable[[Context], PatternResult]]:
    unknown = set(data) - set(DATA_KINDS)
    if unknown:
        raise ValueError(f"unknown data kinds: {sorted(unknown)}")

    def register(fn: Callable[[Context], PatternResult]) -> Callable[[Context], PatternResult]:
        if key in REGISTRY:
            raise ValueError(f"pattern {key!r} registered twice")
        REGISTRY[key] = PatternSpec(key, number, title, min_days, data, method, fn)
        return fn

    return register


def run(key: str, ctx: Context) -> PatternResult:
    spec = REGISTRY[key]
    lo, hi = ctx.span
    days = ctx.days
    basis = {
        "key": spec.key,
        "title": spec.title,
        "method": spec.method,
        "days_used": days,
        "first_day": lo,
        "last_day": hi,
    }
    if days < spec.min_days:
        missing = spec.min_days - days
        return PatternResult(
            **basis, needs_days=missing, ready_on=(hi or ctx.end) + timedelta(days=missing)
        )
    result = spec.fn(ctx)
    method = spec.method + (f" {result.note}" if result.note else "")
    return replace(result, **basis | {"method": method})
