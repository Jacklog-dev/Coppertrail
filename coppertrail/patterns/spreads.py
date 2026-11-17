"""Pattern 7: processing spreads (HANDOVER section 6), product value against input cost.

Per recipe whose product or a reagent is in the selection: product value = mean
result quantity x price x 0.95 (the 5 % auction cut), input cost = sum of reagent
quantity x price. Daily prices are the CET-day medians of hourly min; "now" uses the
latest snapshot min buyout. Reagents outside the selection are priced too.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.common import daily_prices, finish_ranked, names, pct
from coppertrail.query.groups import ItemGroup, starter_groups

KEY = "processing_spreads"
CUT = 0.05  # auction house cut on the product sale
WORTH = 0.10  # a day is worth it when margin_pct >= 10 %
MEAN_DAYS = 30  # the mean covers the last 30 priced days
CHAIN_GROUP = "Leather chain"

RANKED_COLS = [
    "spell_id",
    "recipe",
    "profession",
    "ratio",
    "chain",
    "value_now",
    "cost_now",
    "margin_now",
    "margin_pct_now",
    "mean_margin_30d",
    "mean_pct_30d",
    "days_priced",
    "days_worth",
    "worth_share",
    "sales_per_day",
]
SPREAD_COLS = ["spell_id", "item_id", "day", "value", "cost", "margin"]
DAILY_COLS = ["spell_id", "item_id", "day", "margin", "margin_pct", "worth"]


def _qty(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def _num(x) -> float:
    return float(x) if pd.notna(x) else np.nan


def _product_qty(qmin: float, qmax: float) -> tuple[float, str]:
    """(mean quantity, display text); missing or zero quantities count as 1."""
    lo = qmin if np.isfinite(qmin) and qmin > 0 else np.nan
    hi = qmax if np.isfinite(qmax) and qmax > 0 else np.nan
    lo, hi = (lo if np.isfinite(lo) else hi), (hi if np.isfinite(hi) else lo)
    if not np.isfinite(lo):
        return 1.0, "1"
    text = _qty(lo) if lo == hi else f"{_qty(lo)}-{_qty(hi)}"
    return (lo + hi) / 2, text


def _chain_group() -> ItemGroup:
    by_name = {g.name: g for g in starter_groups()}
    return by_name.get(CHAIN_GROUP, ItemGroup(CHAIN_GROUP))


def _empty_result(note: str, checked: int = 0) -> PatternResult:
    return PatternResult(
        ranked=pd.DataFrame(columns=["item_id", "name", *RANKED_COLS]),
        charts={
            "spread": pd.DataFrame(columns=SPREAD_COLS),
            "daily_margin": pd.DataFrame(columns=DAILY_COLS),
        },
        items_checked=checked,
        note=note,
    )


@pattern(
    KEY,
    number=7,
    title="Processing spreads",
    min_days=1,
    data=("recipes", "hourly", "snapshot", "items"),
    method=(
        "Recipes whose product or a reagent is in the selection. Value = mean result "
        "quantity x price x 0.95, cost = sum of reagent quantity x price; margin = value "
        "- cost, margin % = margin / cost. Daily price = CET-day median of hourly min, a "
        "day counts only when every item is priced; now = latest snapshot min buyout "
        "(fallback: last priced day). 30 d mean over the last 30 priced days. Recipes "
        "with priced days rank first, then by margin % now; chain = the product is in "
        "the Leather chain starter group."
    ),
)
def processing_spreads(ctx: Context) -> PatternResult:
    rec = ctx.recipes
    if rec.empty:
        return _empty_result("No recipes collected yet.")
    rec = rec.dropna(subset=["spell_id", "result_id"])
    if ctx.item_ids is not None:
        sel = set(ctx.item_ids)
        hit = rec["result_id"].isin(sel) | rec["reagent_id"].isin(sel)
        rec = rec[rec["spell_id"].isin(rec.loc[hit, "spell_id"])]
    if rec.empty:
        return _empty_result("No recipe uses or makes a selected item.")

    ids = set(rec["result_id"].astype("int64")) | set(rec["reagent_id"].dropna().astype("int64"))
    daily = daily_prices(ctx.hourly_of(ids))
    wide = (
        daily.pivot(index="day", columns="item_id", values="price").sort_index()
        if len(daily)
        else pd.DataFrame()
    )
    last_day = wide.ffill().iloc[-1] if len(wide) else pd.Series(dtype="float64")
    snap = ctx.snapshot_of(ids)
    sales = snap.groupby("item_id")["sales_per_day"].last().astype("float64")
    snap = snap[snap["min_buyout"].notna() & (snap["min_buyout"] > 0)]
    now_price = snap.set_index("item_id")["min_buyout"].astype("float64")
    now_price = now_price.combine_first(last_day.dropna())

    chain = _chain_group()
    rows, spread, dm = [], [], []
    skipped = 0
    spells = rec.groupby("spell_id", sort=True)
    for spell_id, g in spells:
        first = g.iloc[0]
        pid = int(first["result_id"])
        pname = str(first["result_name"]) if pd.notna(first["result_name"]) else str(pid)
        qty, qty_text = _product_qty(_num(first["result_qty_min"]), _num(first["result_qty_max"]))
        reag = g.dropna(subset=["reagent_id"])
        reagents = [
            (
                int(r.reagent_id),
                str(r.reagent_name) if pd.notna(r.reagent_name) else str(int(r.reagent_id)),
                _num(r.reagent_qty) if pd.notna(r.reagent_qty) else 1.0,
            )
            for r in reag.itertuples()
        ]
        all_ids = [pid] + [rid for rid, _, _ in reagents]
        if not reagents or any(i not in now_price.index for i in all_ids):
            skipped += 1
            continue

        value_now = qty * now_price[pid] * (1 - CUT)
        cost_now = sum(q * now_price[rid] for rid, _, q in reagents)
        margin_now = value_now - cost_now
        pct_now = margin_now / cost_now if cost_now > 0 else np.nan

        if len(wide) and all(i in wide.columns for i in all_ids):
            value = qty * wide[pid] * (1 - CUT)
            cost = sum(q * wide[rid] for rid, _, q in reagents)
            ok = value.notna() & cost.notna()
            value, cost = value[ok], cost[ok]
        else:
            value = cost = pd.Series(dtype="float64")
        margin = value - cost
        mpct = (margin / cost.where(cost > 0)).astype("float64")
        worth = mpct >= WORTH
        tail = margin.tail(MEAN_DAYS)
        days_priced, days_worth = len(margin), int(worth.sum())
        days = list(margin.index)
        spread.append(
            pd.DataFrame(
                {
                    "spell_id": int(spell_id),
                    "item_id": pid,
                    "day": days,
                    "value": value.to_numpy(),
                    "cost": cost.to_numpy(),
                    "margin": margin.to_numpy(),
                }
            )
        )
        dm.append(
            pd.DataFrame(
                {
                    "spell_id": int(spell_id),
                    "item_id": pid,
                    "day": days,
                    "margin": margin.to_numpy(),
                    "margin_pct": mpct.to_numpy(),
                    "worth": worth.to_numpy(),
                }
            )
        )
        # By product only: a reagent match would tag every recipe using Light Leather.
        in_chain = chain.matches(SimpleNamespace(item_id=pid, name=pname))
        ratio = " + ".join(f"{_qty(q)} x {rn}" for _, rn, q in reagents)
        rows.append(
            {
                "item_id": pid,
                "result_name": pname,
                "spell_id": int(spell_id),
                "recipe": first["recipe_name"] if pd.notna(first["recipe_name"]) else pname,
                "profession": first["profession"],
                "ratio": f"{ratio} -> {qty_text} {pname}",
                "chain": CHAIN_GROUP if in_chain else "",
                "value_now": float(value_now),
                "cost_now": float(cost_now),
                "margin_now": float(margin_now),
                "margin_pct_now": float(pct_now),
                "mean_margin_30d": float(tail.mean()) if len(tail) else np.nan,
                "mean_pct_30d": float(mpct.tail(MEAN_DAYS).mean()) if len(tail) else np.nan,
                "days_priced": days_priced,
                "days_worth": days_worth,
                "worth_share": days_worth / days_priced if days_priced else np.nan,
            }
        )

    considered = spells.ngroups
    skip_note = f"{skipped} recipes skipped: unpriced reagent or product."
    if not rows:
        return _empty_result(f"{considered} recipes considered. {skip_note}", checked=considered)

    # Recipes with a priced history first: a product without hourly data (often a
    # crafted item nobody buys) has only a snapshot price, which can be a fantasy listing.
    df = pd.DataFrame(rows)
    df = df.assign(_hist=df["days_priced"] > 0).sort_values(
        ["_hist", "margin_pct_now"], ascending=False, na_position="last", kind="stable"
    )
    df = df.drop(columns="_hist").reset_index(drop=True)
    ranked = finish_ranked(df, ctx, RANKED_COLS)
    unknown = ~ranked["item_id"].isin(names(ctx)["item_id"])
    ranked.loc[unknown, "name"] = df.loc[unknown, "result_name"]
    ranked["sales_per_day"] = ranked["item_id"].map(sales)  # products outside the selection too
    hits = (
        (df["margin_now"] > 0)
        & (df["days_priced"] > 0)
        & (df["days_worth"] >= df["days_priced"] / 2)
    )
    return PatternResult(
        ranked=ranked,
        charts={
            "spread": pd.concat(spread, ignore_index=True)[SPREAD_COLS],
            "daily_margin": pd.concat(dm, ignore_index=True)[DAILY_COLS],
        },
        items_checked=considered,
        items_hit=int(hits.sum()),
        note=(
            f"Worth it: margin {pct(WORTH)} or more of input cost (threshold {WORTH:.2f}). "
            f"Hit: margin now above 0 and worth it on at least half the priced days. "
            f"{considered} recipes considered. {skip_note}"
        ),
    )
