"""Which items the hourly run stores: Jack's rules from `[selection]`, plus a safety cap.

The class and quality rules use item details; `min_median` uses the snapshot's median.
The cap only applies above `max_items`: candidates rank by traded gold, and an item
already in the selection stays while it ranks within `keep_rank`.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

from .config import QUALITY_ORDER, Selection
from .store import SELECTION, Store

_RANK = {q: i for i, q in enumerate(QUALITY_ORDER)}


def _missing(value) -> bool:
    if value is None or value is pd.NA:
        return True
    return isinstance(value, float) and math.isnan(value)


def passes(detail: dict | None, median: int | None, sel: Selection) -> str | None:
    """Return "rule" or "unclassified" when the item is selected, else None."""
    if detail is None or not detail.get("found", True):
        return "unclassified" if sel.include_unclassified else None
    quality = detail.get("quality")
    cls = detail.get("class")
    if quality in sel.exclude_qualities:
        return None
    if cls in sel.exclude_classes:
        return None
    below = _RANK.get(quality, -1) < _RANK[sel.equipment_min_quality]
    if cls in sel.equipment_classes and below:
        return None
    floor = sel.min_median.get(quality)
    if floor is not None and (_missing(median) or median < floor):
        return None
    return "rule"


def build_selection(
    summary: pd.DataFrame,
    details: pd.DataFrame,
    traded: pd.Series | None,
    sel: Selection,
    previous: set[int],
    day: date,
) -> pd.DataFrame:
    """The selection for `day` in the SELECTION schema (`rank` is NULL without a cap)."""
    by_id = {}
    if not details.empty:
        for rec in details.to_dict("records"):
            by_id[int(rec["item_id"])] = rec
    chosen = []
    for item_id, median in zip(summary["item_id"], summary["median"], strict=True):
        median = None if _missing(median) else int(median)
        reason = passes(by_id.get(int(item_id)), median, sel)
        if reason is not None:
            chosen.append((int(item_id), reason))
    df = pd.DataFrame(chosen, columns=["item_id", "reason"])
    df["rank"] = pd.array([pd.NA] * len(df), dtype="Int32")

    if len(df) > sel.max_items:
        value = df["item_id"].map(traded if traded is not None else {}).fillna(0)
        df = df.assign(_value=value).sort_values(
            ["_value", "item_id"], ascending=[False, True], kind="stable"
        )
        df["rank"] = pd.array(range(1, len(df) + 1), dtype="Int32")
        keep = df["item_id"].isin(previous) & (df["rank"] <= sel.keep_rank)
        room = max(sel.max_items - int(keep.sum()), 0)
        fill = df[~keep].head(room)
        df = pd.concat([df[keep], fill]).drop(columns="_value")

    df = df.sort_values("item_id", kind="stable").reset_index(drop=True)
    df.insert(0, "day", day)
    return df[["day", "item_id", "reason", "rank"]]


def current_selection(store: Store) -> set[int] | None:
    """The item ids of the newest selection file, or None when there is none."""
    files = store.files(SELECTION)
    if not files:
        return None
    tbl = store.read(SELECTION, *(2 * [date.fromisoformat(files[-1].stem)]))
    return {int(i) for i in tbl.column("item_id").to_pylist()}
