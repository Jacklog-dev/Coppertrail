"""Gap report: hours without hourly data per watchlist item over a recent window."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .store import HOURLY, Store


def hour_floor(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def _ranges(hours: list[datetime]) -> list[tuple[datetime, datetime]]:
    """Collapse sorted hours into inclusive (start, end) runs."""
    out: list[tuple[datetime, datetime]] = []
    for h in hours:
        if out and h - out[-1][1] == timedelta(hours=1):
            out[-1] = (out[-1][0], h)
        else:
            out.append((h, h))
    return out


def gap_report(
    store: Store, item_ids: list[int], end: datetime, window_hours: int, run_id: str
) -> tuple[list[dict], list[tuple[datetime, datetime]]]:
    """Per-item gap rows and the market-wide gaps (hours with no data for any item).

    The window ends at the last full hour before `end`. Hours before an item's first
    observation inside the window still count as missing: the archive has a hole there.
    """
    window_end = hour_floor(end) - timedelta(hours=1)
    window_start = window_end - timedelta(hours=window_hours - 1)
    expected = [window_start + timedelta(hours=i) for i in range(window_hours)]

    present: dict[int, set[datetime]] = defaultdict(set)
    tbl = store.query(
        "SELECT item_id, hour FROM {h} WHERE hour BETWEEN ? AND ?",
        [window_start, window_end],
        h=HOURLY.name,
    )
    if tbl is not None:
        for iid, h in zip(
            tbl.column("item_id").to_pylist(), tbl.column("hour").to_pylist(), strict=True
        ):
            present[iid].add(h)

    rows = []
    any_hours: set[datetime] = set()
    for iid in item_ids:
        hs = present.get(iid, set())
        any_hours |= hs
        missing = [h for h in expected if h not in hs]
        longest = max(
            (int((b - a).total_seconds() // 3600) + 1 for a, b in _ranges(missing)), default=0
        )
        rows.append(
            {
                "run_id": run_id,
                "report_at": end,
                "item_id": iid,
                "window_start": window_start,
                "window_end": window_end,
                "hours_expected": window_hours,
                "hours_present": len(hs),
                "hours_missing": len(missing),
                "longest_gap_hours": longest,
                "first_hour": min(hs) if hs else None,
                "last_hour": max(hs) if hs else None,
            }
        )
    market_gaps = _ranges([h for h in expected if h not in any_hours])
    return rows, market_gaps


def format_summary(rows: list[dict], market_gaps: list[tuple[datetime, datetime]]) -> str:
    if not rows:
        return "Gap report: no items."
    n = len(rows)
    full = sum(1 for r in rows if r["hours_missing"] == 0)
    empty = sum(1 for r in rows if r["hours_present"] == 0)
    missing = sorted(r["hours_missing"] for r in rows)
    median = missing[n // 2]
    lines = [
        f"Gap report ({rows[0]['window_start']:%Y-%m-%d %H:%M} to "
        f"{rows[0]['window_end']:%Y-%m-%d %H:%M} UTC, {rows[0]['hours_expected']} h): "
        f"{n} items, {full} complete, {empty} with no data, median {median} h missing.",
    ]
    if market_gaps:
        spans = ", ".join(
            f"{a:%m-%d %H:00}" + (f"-{b:%H:00}" if b != a else "") for a, b in market_gaps
        )
        hours = sum(int((b - a).total_seconds() // 3600) + 1 for a, b in market_gaps)
        lines.append(f"Market-wide hours with no data for any item ({hours} h): {spans}")
    else:
        lines.append("Market-wide: every hour has data for at least one item.")
    worst = sorted(rows, key=lambda r: -r["hours_missing"])[:10]
    lines.append(
        "Most missing: "
        + ", ".join(f"{r['item_id']} ({r['hours_missing']} h)" for r in worst if r["hours_missing"])
    )
    return "\n".join(lines)
