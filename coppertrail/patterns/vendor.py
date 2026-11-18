"""Pattern 10: vendor floor, hours when the min buyout sits at or below the vendor price.

The vendor price is `vendorSell` (copper a vendor pays per unit). Buying below it and
selling to a vendor is risk-free: no auction house cut applies when vendoring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.common import by_hour, finish_ranked, local_hour

NEAR = 0.10  # an hour is near when min <= vendor price x 1.10

RANKED_COLS = [
    "vendor_price",
    "min_now",
    "ratio_now",
    "lowest_ratio",
    "hours",
    "hours_near",
    "hours_below",
    "share_near",
    "last_near_at",
    "best_hour",
    "sales_per_day",
]
HOURS_COLS = ["item_id", "hour", "min", "vendor_price", "ratio", "near", "below"]


def _vendor_prices(ctx: Context) -> pd.Series:
    """vendor_price per item (index item_id), only items with a price above 0."""
    d = ctx.details
    if d.empty:
        return pd.Series(dtype="float64", name="vendor_price")
    v = d.set_index("item_id")["vendor_price"].astype("float64")
    return v[v > 0]


def _empty_result(note: str) -> PatternResult:
    return PatternResult(
        ranked=pd.DataFrame(columns=["item_id", "name", *RANKED_COLS]),
        charts={"hours": pd.DataFrame(columns=HOURS_COLS), "by_hour": by_hour(pd.DataFrame())},
        note=note,
    )


@pattern(
    "vendor_floor",
    number=10,
    title="Vendor floor",
    min_days=1,
    data=("hourly", "latest", "items"),
    method=(
        "Vendor price = what a vendor pays per unit (vendorSell). Per item and hour the "
        f"hourly min against it: near at or below {1 + NEAR:.0%} of the vendor price, "
        "below under 100% (buy and vendor is risk-free, no auction house cut). Current "
        "ratio from the latest snapshot min buyout (fallback: last hourly min); items "
        "without hourly data are checked on that snapshot only."
    ).replace("%", " %"),
)
def vendor_floor(ctx: Context) -> PatternResult:
    h = ctx.hourly
    if h.empty:
        return _empty_result("No hourly data in the range.")
    vendor = _vendor_prices(ctx)
    ids = pd.Index(h["item_id"].unique())
    skipped = int((~ids.isin(vendor.index)).sum())
    skip_note = f" {skipped} items skipped: no vendor price." if skipped else ""
    if vendor.empty:
        return _empty_result(
            "No vendor prices yet (the collector fills them from its next run)." + skip_note
        )
    h = h[h["item_id"].isin(vendor.index)][["item_id", "hour", "min"]].copy()
    h["vendor_price"] = h["item_id"].map(vendor)
    h["min"] = h["min"].astype("float64")
    h["ratio"] = h["min"] / h["vendor_price"]
    h["near"] = h["min"] <= h["vendor_price"] * (1 + NEAR)
    h["below"] = h["min"] < h["vendor_price"]
    h = h.sort_values(["item_id", "hour"]).reset_index(drop=True)

    near = h[h["near"]]
    g = h.groupby("item_id")
    per = pd.DataFrame(
        {
            "vendor_price": g["vendor_price"].first(),
            "lowest_ratio": g["ratio"].min(),
            "hours": g["min"].count(),
            "hours_near": g["near"].sum().astype("int64"),
            "hours_below": g["below"].sum().astype("int64"),
            "last_min": g["min"].last(),
        }
    )
    per["share_near"] = per["hours_near"] / per["hours"]
    per["last_near_at"] = near.groupby("item_id")["hour"].max().reindex(per.index)
    per["last_near_at"] = pd.to_datetime(per["last_near_at"], utc=True)
    if len(near):
        # CET hour of day with the most near hours; ties go to the earliest hour.
        counts = near.assign(lh=local_hour(near["hour"])).groupby(["item_id", "lh"]).size()
        best = counts.reset_index(name="n").sort_values(
            ["item_id", "n", "lh"], ascending=[True, False, True]
        )
        best = best.drop_duplicates("item_id").set_index("item_id")["lh"]
        per["best_hour"] = best.reindex(per.index).astype("float64")
    else:
        per["best_hour"] = np.nan
    snap = ctx.latest
    snap_min = (
        snap.set_index("item_id")["min_buyout"].astype("float64")
        if not snap.empty
        else pd.Series(dtype="float64")
    )
    per["min_now"] = snap_min.reindex(per.index).fillna(per["last_min"])
    per["ratio_now"] = per["min_now"] / per["vendor_price"]
    # Items without hourly rows in the range: the latest hour still shows whether they
    # sit on the floor now.
    only = vendor.index.difference(per.index).intersection(snap_min.dropna().index)
    if len(only):
        so = pd.DataFrame(index=only.rename("item_id"))
        so["vendor_price"] = vendor.reindex(only)
        so["min_now"] = snap_min.reindex(only)
        so["ratio_now"] = so["min_now"] / so["vendor_price"]
        so["lowest_ratio"] = so["ratio_now"]
        so[["hours", "hours_near", "hours_below"]] = 0
        so["share_near"] = np.nan
        so["best_hour"] = np.nan
        at = snap.groupby("item_id")["observed_at"].max().reindex(only)
        so["last_near_at"] = at.where(so["ratio_now"] <= 1 + NEAR)
        per = pd.concat([per, so])
        for c in ("hours", "hours_near", "hours_below"):
            per[c] = per[c].astype("int64")
    per["now_near"] = per["ratio_now"] <= 1 + NEAR
    per = per.sort_values(["lowest_ratio", "hours_near"], ascending=[True, False])
    ranked = finish_ranked(per.reset_index(), ctx, RANKED_COLS)

    hits = int(((per["hours_near"] >= 1) | per["now_near"]).sum())
    return PatternResult(
        ranked=ranked,
        charts={
            "hours": h[HOURS_COLS],
            "by_hour": by_hour(near.rename(columns={"hour": "at"})),
        },
        items_checked=len(per),
        items_hit=hits,
        note=(
            f"Hit: at least one hour (or the latest snapshot) with min at or below "
            f"{1 + NEAR:.0%} of the vendor price. {int(per['hours_below'].gt(0).sum())} items "
            f"went below it. {len(only)} items without hourly data checked on the latest "
            "snapshot only (hours = 0)."
        ).replace("%", " %")
        + skip_note,
    )
