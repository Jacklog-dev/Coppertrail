"""Pattern 8: progression wave, price and supply per level band and the supply turning point."""

from __future__ import annotations

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.common import finish_ranked, local_day

MIN_HOURS = 12  # a CET day counts with at least 12 hourly rows
MIN_BASE_QTY = 20  # items listed thinner than this on the base day are left out
PEAK_GROWTH = 0.05  # a growth phase needs smoothed supply growth of 5 %/day or more
FLAT_SHARE = 0.25  # flattened: growth below a quarter of the peak
BANDS = [(1, 9), (10, 19), (20, 29), (30, 39), (40, 49), (50, 59), (60, 60)]

RANKED_COLS = [
    "level",
    "band",
    "days",
    "price_change",
    "supply_change",
    "peak_growth",
    "peak_day",
    "turning_day",
    "sales_per_day",
]


def band_of(level: float) -> str | None:
    if level is None or not np.isfinite(level):
        return None
    for lo, hi in BANDS:
        if lo <= level <= hi:
            return f"{lo}-{hi}" if lo != hi else str(lo)
    return None


def turning_point(supply: pd.Series) -> tuple[float, object, object]:
    """(peak growth, peak day, turning day) for a supply series indexed by day.

    Growth = day-over-day change, smoothed over 2 days. The turning point is the first
    day after the peak where smoothed growth drops below FLAT_SHARE of the peak and stays
    there the next day too (so the last day alone never makes a turning point).
    """
    g = (supply / supply.shift() - 1).rolling(2, min_periods=2).mean().dropna()
    if g.empty:
        return np.nan, None, None
    peak_day = g.idxmax()
    peak = float(g.loc[peak_day])
    if peak < PEAK_GROWTH:
        return peak, peak_day, None
    after = g.loc[g.index > peak_day] < FLAT_SHARE * peak
    held = after & after.shift(-1, fill_value=False)
    return peak, peak_day, (held.index[held.to_numpy()][0] if held.any() else None)


def daily(h: pd.DataFrame) -> pd.DataFrame:
    h = h.assign(day=local_day(h["hour"]))
    d = h.groupby(["item_id", "day"]).agg(
        n=("min", "size"), min=("min", "mean"), quantity=("quantity", "mean")
    )
    return d[d["n"] >= MIN_HOURS].drop(columns="n").reset_index()


def _relative(d: pd.DataFrame) -> pd.DataFrame:
    """Index against one base day (the first full day in the range) for every item.

    Items missing on the base day, or listed thinner than MIN_BASE_QTY, are dropped, so a
    band median never mixes items indexed to different days.
    """
    if d.empty:
        return d.assign(price_idx=pd.Series(dtype=float), supply_idx=pd.Series(dtype=float))
    base = d[d["day"] == d["day"].min()].set_index("item_id")
    base = base[(base["quantity"] >= MIN_BASE_QTY) & (base["min"] > 0)]
    d = d[d["item_id"].isin(base.index)]
    return d.assign(
        price_idx=100 * d["min"] / d["item_id"].map(base["min"]),
        supply_idx=100 * d["quantity"] / d["item_id"].map(base["quantity"]),
    )


@pattern(
    "progression_wave",
    number=8,
    title="Progression wave",
    min_days=3,
    data=("hourly", "items", "snapshot"),
    method=(
        "CET days with at least 12 hourly rows; per item the daily mean min and quantity, "
        "per level band the median over items of value / first day x 100. Turning point: "
        "first day after the peak of 2-day smoothed supply growth (at least 5 %/day) where "
        "growth falls below a quarter of the peak for two days running."
    ),
)
def progression_wave(ctx: Context) -> PatternResult:
    h = ctx.hourly
    if h.empty:
        return PatternResult(note="No hourly data in the range.")
    levels = ctx.items.set_index("item_id")["level"]
    d = daily(h)
    d["band"] = d["item_id"].map(levels).map(band_of)
    d = _relative(d.dropna(subset=["band"]))
    order = {f"{lo}-{hi}" if lo != hi else str(lo): i for i, (lo, hi) in enumerate(BANDS)}

    bands = (
        d.groupby(["band", "day"])
        .agg(
            price_idx=("price_idx", "median"),
            supply_idx=("supply_idx", "median"),
            quantity=("quantity", "sum"),
            items=("item_id", "nunique"),
        )
        .reset_index()
    )
    bands = bands.sort_values(
        ["band", "day"], key=lambda s: s.map(order) if s.name == "band" else s
    )
    tps = []
    for band, g in bands.groupby("band", sort=False):
        peak, peak_day, turn = turning_point(g.set_index("day")["supply_idx"])
        last = g.iloc[-1]
        tps.append(
            {
                "band": band,
                "items": int(g["items"].max()),
                "price_change": last["price_idx"] / 100 - 1,
                "supply_change": last["supply_idx"] / 100 - 1,
                "peak_growth": peak,
                "peak_day": peak_day,
                "turning_day": turn,
            }
        )
    tp = pd.DataFrame(
        tps,
        columns=[
            "band",
            "items",
            "price_change",
            "supply_change",
            "peak_growth",
            "peak_day",
            "turning_day",
        ],
    )

    rows = []
    for item_id, g in d.groupby("item_id"):
        g = g.sort_values("day")
        peak, peak_day, turn = turning_point(g.set_index("day")["quantity"])
        rows.append(
            {
                "item_id": int(item_id),
                "level": levels.get(item_id),
                "band": g["band"].iloc[0],
                "days": len(g),
                "price_change": g["price_idx"].iloc[-1] / 100 - 1,
                "supply_change": g["supply_idx"].iloc[-1] / 100 - 1,
                "peak_growth": peak,
                "peak_day": peak_day,
                "turning_day": turn,
            }
        )
    per = pd.DataFrame(rows, columns=["item_id", *RANKED_COLS[:-1]])
    if per.empty:
        return PatternResult(
            charts={"bands": bands, "turning_points": tp},
            items_checked=int(h["item_id"].nunique()),
            note="No item has full CET days and a level.",
        )
    per["hit"] = per["turning_day"].notna()
    per = per.sort_values(["hit", "supply_change"], ascending=False)
    ranked = finish_ranked(per, ctx, RANKED_COLS)
    turned = tp.loc[tp["turning_day"].notna(), "band"].tolist()
    return PatternResult(
        ranked=ranked,
        charts={"bands": bands, "turning_points": tp},
        items_checked=int(h["item_id"].nunique()),
        items_hit=int(per["hit"].sum()),
        note=(
            f"Bands with a turning point: {', '.join(turned) or 'none'}. "
            "Items without a level, or missing or thinner than "
            f"{MIN_BASE_QTY} units on the base day, are left out."
        ),
    )
