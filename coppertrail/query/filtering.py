"""Apply the filter bar to the item catalog, and resolve the date range against the archive."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from coppertrail.query.catalog import ArchiveStatus, Item
from coppertrail.query.groups import ItemGroup
from coppertrail.query.settings import Filters

RANGE_DAYS = {"24h": 1, "7d": 7, "30d": 30}


def apply_filters(items: Sequence[Item], groups: Sequence[ItemGroup], f: Filters) -> list[Item]:
    """Items passing every item filter. The date range does not drop items; views use it.

    Selected groups combine as a union ("Leather chain, Herbs" = items in either);
    names of groups that no longer exist are ignored.
    """
    selected = [g for g in groups if g.name in set(f.groups)]
    needle = f.search.strip().casefold()
    out = []
    for item in items:
        if selected and not any(g.matches(item) for g in selected):
            continue
        if f.item_class and item.item_class != f.item_class:
            continue
        if needle and needle not in item.name.casefold():
            continue
        if f.min_sales and item.sales_per_day < f.min_sales:
            continue
        out.append(item)
    return out


def item_classes(items: Sequence[Item]) -> list[str]:
    """Classes present in the catalog, most items first."""
    counts: dict[str, int] = {}
    for i in items:
        if i.item_class:
            counts[i.item_class] = counts.get(i.item_class, 0) + 1
    return sorted(counts, key=lambda c: (-counts[c], c))


def date_window(f: Filters, status: ArchiveStatus, today: date | None = None) -> tuple[date, date]:
    """The (from, to) days a view should show, inclusive.

    Presets end on the archive's last day (or today without data). Every range is
    clamped to the archive, so a view never claims days it has no data for: with
    eight days archived, "30 d" shows those eight days.
    """
    end = status.last_day or today or date.today()
    start_of_archive = status.first_day or end
    if f.range == "custom" and f.date_from and f.date_to:
        lo, hi = sorted((f.date_from, f.date_to))
        if status.first_day and status.last_day:
            lo = min(max(lo, status.first_day), status.last_day)
            hi = min(max(hi, status.first_day), status.last_day)
        return lo, hi
    if f.range == "all":
        return start_of_archive, end
    days = RANGE_DAYS.get(f.range, 30)
    start = end - timedelta(days=days - 1)
    if status.first_day:
        start = max(start, status.first_day)
    return start, end
