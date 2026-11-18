"""Pattern 12: inflation (HANDOVER section 7), turnover-weighted basket indexes per group.

Groups: farmable (the Herbs, Leather chain, Cloth and Ore and bars starter groups,
minus scarce goods), scarce (the Scarce goods starter group) and vendor-tied (the
name list below, a stopgap until vendor prices are collected). The starter
definitions are used, not the user's edited groups, so the index stays comparable.
Gold listed and auctions come from the house rows (one per snapshot).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.common import daily_prices, finish_ranked, local_day, sales_per_day
from coppertrail.query.groups import ItemGroup, starter_groups

FARMABLE_GROUPS = ("Herbs", "Leather chain", "Cloth", "Ore and bars")
SCARCE_GROUP = "Scarce goods"
VENDOR_TIED = [
    "Coarse Thread",
    "Fine Thread",
    "Silken Thread",
    "Heavy Silken Thread",
    "Rune Thread",
    "Gray Dye",
    "Blue Dye",
    "Red Dye",
    "Yellow Dye",
    "Black Dye",
    "Green Dye",
    "Purple Dye",
    "Orange Dye",
    "Pink Dye",
    "Empty Vial",
    "Leaded Vial",
    "Crystal Vial",
    "Imbued Vial",
    "Weak Flux",
    "Strong Flux",
    "Salt",
    "Simple Flour",
    "Mild Spices",
    "Hot Spices",
    "Soothing Spices",
    "Refreshing Spring Water",
    "Ice Cold Milk",
    "Melon Juice",
    "Sweet Nectar",
    "Moonberry Juice",
    "Morning Glory Dew",
    "Rough Arrow",
    "Sharp Arrow",
    "Razor Arrow",
    "Light Shot",
    "Heavy Shot",
    "Solid Shot",
    "Copper Rod",
]
GROUPS = ("farmable", "scarce", "vendor")
MOVE = 0.05  # an item "fits the hypothesis" when it moved 5 % the predicted way

RANKED_COLS = ["group", "weight", "base_price", "last_price", "price_change", "contribution"]


def classify(items: pd.DataFrame) -> pd.Series:
    """item_id -> 'farmable' / 'scarce' / 'vendor' (others left out)."""
    by_name = {g.name: g for g in starter_groups()}
    farm = [by_name[n] for n in FARMABLE_GROUPS if n in by_name]
    scarce = by_name.get(SCARCE_GROUP, ItemGroup(SCARCE_GROUP))
    vendor = ItemGroup("Vendor-tied", patterns=VENDOR_TIED)
    out = {}
    for r in items.itertuples():
        it = SimpleNamespace(item_id=int(r.item_id), name=str(r.name))
        if scarce.matches(it):
            out[it.item_id] = "scarce"
        elif vendor.matches(it):
            out[it.item_id] = "vendor"
        elif any(g.matches(it) for g in farm):
            out[it.item_id] = "farmable"
    return pd.Series(out, name="group", dtype="object")


def basket(prices: pd.DataFrame, groups: pd.Series, sales: pd.Series) -> tuple:
    """(index frame, per-item frame). Base day = first day in `prices`."""
    p = prices[prices["item_id"].isin(groups.index)].copy()
    if p.empty:
        return pd.DataFrame(columns=["day", "group", "index", "items"]), pd.DataFrame()
    base_day = p["day"].min()
    base = p[p["day"] == base_day].set_index("item_id")["price"]
    p = p[p["item_id"].isin(base.index)]
    p["group"] = p["item_id"].map(groups)
    p["rel"] = p["price"] / p["item_id"].map(base)
    turnover = (sales.reindex(base.index).fillna(0) * base).rename("turnover")
    w = turnover.groupby(groups.reindex(base.index)).transform(
        lambda t: t / t.sum() if t.sum() > 0 else 1 / len(t)
    )
    p["w"] = p["item_id"].map(w)
    rows = []
    for (day, group), g in p.groupby(["day", "group"]):
        rows.append(
            {
                "day": day,
                "group": group,
                "index": 100 * float((g["w"] * g["rel"]).sum() / g["w"].sum()),
                "items": len(g),
            }
        )
    idx = pd.DataFrame(rows).sort_values(["group", "day"]).reset_index(drop=True)
    last = p.sort_values("day").groupby("item_id").tail(1).set_index("item_id")
    per = pd.DataFrame(
        {
            "group": groups.reindex(base.index),
            "weight": w,
            "base_price": base,
            "last_price": last["price"].reindex(base.index),
        }
    )
    per["price_change"] = per["last_price"] / per["base_price"] - 1
    per["contribution"] = per["weight"] * per["price_change"]
    return idx, per.rename_axis("item_id").reset_index()


def economy_chart(house: pd.DataFrame, base_day=None) -> pd.DataFrame:
    """Per CET day the median over the house rows (one per snapshot) of gold listed (in
    gold), auctions and units; gold_index = 100 on `base_day` (or day one)."""
    if house.empty:
        return pd.DataFrame(columns=["day", "gold_listed", "auctions", "units", "gold_index"])
    h = house.assign(day=local_day(house["hour"]))
    out = (
        h.groupby("day")
        .agg(
            gold_listed=("gold_listed", lambda v: v.astype("float64").median() / 10_000),
            auctions=("auctions", "median"),
            units=("units", "median"),
        )
        .reset_index()
    )
    at_base = out.loc[out["day"] == base_day, "gold_listed"] if base_day is not None else []
    base = at_base.iloc[0] if len(at_base) else out["gold_listed"].iloc[0]
    out["gold_index"] = 100 * out["gold_listed"] / base if base else np.nan
    return out


@pattern(
    "inflation",
    number=12,
    title="Inflation",
    min_days=3,
    data=("hourly", "latest", "items", "house"),
    method=(
        "Daily price = CET-day median of hourly min. Basket per group (farmable, scarce, "
        "vendor-tied) weighted by latest sales/day x base-day price; index 100 = first "
        "day, over the items present. Divergence = scarce - farmable. Gold listed and "
        "auctions: CET-day median of the house rows."
    ),
)
def inflation(ctx: Context) -> PatternResult:
    h = ctx.hourly
    if h.empty:
        econ = economy_chart(ctx.house)
        return PatternResult(charts={"economy": econ}, note="No hourly data in the range.")
    groups = classify(ctx.items)
    idx, per = basket(daily_prices(h), groups, sales_per_day(ctx))
    # Same base day as the price indexes, so the charts can be overlaid.
    econ = economy_chart(ctx.house, idx["day"].min() if len(idx) else None)
    wide = idx.pivot(index="day", columns="group", values="index") if len(idx) else None
    div = pd.DataFrame(columns=["day", "divergence"])
    if wide is not None and {"scarce", "farmable"} <= set(wide.columns):
        div = (wide["scarce"] - wide["farmable"]).rename("divergence").reset_index()
    if per.empty:
        return PatternResult(
            charts={"index": idx, "divergence": div, "economy": econ},
            items_checked=int(h["item_id"].nunique()),
            note="No basket item has a full base day.",
        )
    up = per["group"].eq("scarce") & (per["price_change"] >= MOVE)
    down = per["group"].isin(["farmable", "vendor"]) & (per["price_change"] <= -MOVE)
    per["fits"] = up | down
    per = per.sort_values("contribution", key=np.abs, ascending=False)
    ranked = finish_ranked(per, ctx, [*RANKED_COLS, "fits"])
    counts = per["group"].value_counts().reindex(GROUPS, fill_value=0)
    last = div["divergence"].iloc[-1] if len(div) else np.nan
    return PatternResult(
        ranked=ranked,
        charts={"index": idx, "divergence": div, "economy": econ},
        items_checked=len(per),
        items_hit=int(per["fits"].sum()),
        note=(
            f"Basket: {counts['farmable']} farmable, {counts['scarce']} scarce, "
            f"{counts['vendor']} vendor-tied items. Hit: scarce up or farmable/vendor-tied "
            f"down by 5 % or more. Latest divergence "
            f"{'n/a' if not np.isfinite(last) else f'{last:+.1f}'} index points."
        ),
    )
