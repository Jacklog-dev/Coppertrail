"""Pattern 6: mean reversion, daily dips below the trailing 7-day mean and their recovery.

A signal day is a CET day whose price is at least 15 % below the mean of the previous
7 calendar days (at least 5 of them priced). It counts as recovered when a price in
the next 3 days reaches that mean. The base rate is how often any day's price rises
by the same factor (1 / 0.85) within 3 days, so the edge says whether dips recover
more often than prices just bounce around.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.baseline import CUT
from coppertrail.patterns.common import daily_prices, finish_ranked, pct, runs

DROP = 0.15  # signal: price at least 15 % below the trailing mean
WINDOW = 7  # trailing mean over the previous 7 calendar days
MIN_WINDOW = 5  # of which at least 5 priced
HORIZON = 3  # days to recover
HIT_SIGNALS = 3
HIT_RATE = 0.6
HIT_EDGE = 0.10

RANKED_COLS = [
    "signals",
    "recovered",
    "hit_rate",
    "base_rate",
    "edge",
    "median_days",
    "median_return",
    "pending",
]
SIGNAL_COLS = ["item_id", "day", "price", "mean7", "recovered", "days_to_recover", "ret"]
SERIES_COLS = ["item_id", "day", "price", "mean7", "threshold"]


def _full_series(d: pd.DataFrame) -> pd.DataFrame:
    """Per item, every day from the first to the last day in `d` (missing days NaN)."""
    days = [
        d["day"].min() + timedelta(days=i)
        for i in range((d["day"].max() - d["day"].min()).days + 1)
    ]
    idx = pd.MultiIndex.from_product(
        [sorted(d["item_id"].unique()), days], names=["item_id", "day"]
    )
    s = d.set_index(["item_id", "day"])["price"].reindex(idx).reset_index()
    s["mean7"] = s.groupby("item_id")["price"].transform(
        lambda p: p.rolling(WINDOW, min_periods=MIN_WINDOW).mean().shift(1)
    )
    s["threshold"] = s["mean7"] * (1 - DROP)
    return s


def _item(g: pd.DataFrame) -> tuple[list[dict], dict]:
    """(signal rows, per-item stats) for one item's full daily series."""
    p = g["price"].to_numpy()
    m = g["mean7"].to_numpy()
    days = g["day"].to_numpy()
    n = len(p)
    flag = pd.Series(np.isfinite(p) & np.isfinite(m) & (p <= m * (1 - DROP)))
    rid = runs(flag).to_numpy()
    starts = [i for i in range(n) if rid[i] >= 0 and (i == 0 or rid[i - 1] != rid[i])]
    sig, pending = [], 0
    for i in starts:
        if i + HORIZON > n - 1:
            pending += 1
            continue
        fut = p[i + 1 : i + HORIZON + 1]
        reached = np.flatnonzero(np.isfinite(fut) & (fut >= m[i]))
        priced = np.flatnonzero(np.isfinite(fut))
        sell = fut[priced[-1]] if len(priced) else np.nan
        sig.append(
            {
                "item_id": g["item_id"].iloc[0],
                "day": days[i],
                "price": p[i],
                "mean7": m[i],
                "recovered": bool(len(reached)),
                "days_to_recover": float(reached[0] + 1) if len(reached) else np.nan,
                "ret": sell * (1 - CUT) / p[i] - 1,
            }
        )
    # Base rate over every priced day with a full horizon: how often the price rises by
    # the factor a signal needed (mean7 / price, at least 1 / (1 - DROP)) anyway.
    rise = []
    for i in range(max(0, n - HORIZON)):
        fut = p[i + 1 : i + HORIZON + 1]
        if np.isfinite(p[i]) and np.isfinite(fut).any():
            rise.append(np.nanmax(fut) / p[i])
    rise = np.asarray(rise)
    factors = [s["mean7"] / s["price"] for s in sig] or [1 / (1 - DROP)]
    base = float(np.mean([(rise >= f).mean() for f in factors])) if len(rise) else np.nan
    rec = [s for s in sig if s["recovered"]]
    rate = len(rec) / len(sig) if sig else np.nan
    stats = {
        "item_id": g["item_id"].iloc[0],
        "signals": len(sig),
        "recovered": len(rec),
        "hit_rate": rate,
        "base_rate": base,
        "edge": rate - base,
        "median_days": float(np.median([s["days_to_recover"] for s in rec])) if rec else np.nan,
        "median_return": float(np.nanmedian([s["ret"] for s in sig])) if sig else np.nan,
        "pending": pending,
    }
    return sig, stats


def _empty(note: str, checked: int = 0) -> PatternResult:
    return PatternResult(
        ranked=pd.DataFrame(columns=["item_id", "name", *RANKED_COLS]),
        charts={
            "signals": pd.DataFrame(columns=SIGNAL_COLS),
            "series": pd.DataFrame(columns=SERIES_COLS),
        },
        items_checked=checked,
        note=note,
    )


@pattern(
    "mean_reversion",
    number=6,
    title="Mean reversion",
    min_days=21,
    data=("hourly", "snapshot", "items"),
    method=(
        "Daily price = CET-day median of hourly min. Signal: price at least 15 % below the "
        "mean of the previous 7 calendar days (5 priced at least). Recovered: a price in the "
        "next 3 days reaches that mean. Base rate: share of all days whose price rises "
        "within 3 days by the factor each signal needed (mean / price), averaged over "
        "the signals (1 / 0.85 without signals). Return: price 3 days later (or the "
        "last priced day within them) after the 5 % cut, against the signal price."
    ),
)
def mean_reversion(ctx: Context) -> PatternResult:
    d = daily_prices(ctx.hourly)
    if d.empty:
        return _empty("No full CET days of hourly data in the range.")
    s = _full_series(d)
    checked = s.loc[s["mean7"].notna() & s["price"].notna(), "item_id"].unique()
    sigs, stats = [], []
    for _, g in s[s["item_id"].isin(checked)].groupby("item_id", sort=False):
        rows, st = _item(g.reset_index(drop=True))
        sigs += rows
        stats.append(st)
    series_chart = s[SERIES_COLS].reset_index(drop=True)
    if not stats:
        res = _empty("No item has 5 priced days before a priced day.")
        res.charts["series"] = series_chart
        return res
    per = pd.DataFrame(stats)
    pending = int(per["pending"].sum())
    per = per[(per["signals"] > 0) | (per["pending"] > 0)]
    per = per.sort_values(["edge", "signals"], ascending=False, na_position="last")
    per["hit"] = (
        (per["signals"] >= HIT_SIGNALS) & (per["hit_rate"] >= HIT_RATE) & (per["edge"] >= HIT_EDGE)
    )
    hits = int(per["hit"].sum())
    ranked = (
        finish_ranked(per, ctx, RANKED_COLS)
        if len(per)
        else pd.DataFrame(columns=["item_id", "name", *RANKED_COLS])
    )
    signals = pd.DataFrame(sigs, columns=SIGNAL_COLS)
    med = signals["ret"].median() if len(signals) else np.nan
    return PatternResult(
        ranked=ranked,
        charts={"signals": signals, "series": series_chart},
        items_checked=len(checked),
        items_hit=hits,
        note=(
            f"Consecutive signal days count once (the first day of a run). {len(signals)} "
            f"signals with a full 3-day horizon, {pending} pending (horizon past the data, "
            f"left out). Median 3-day return {pct(med)}. Hit: {HIT_SIGNALS}+ signals, hit rate "
            f"{HIT_RATE:.0%} or more and {HIT_EDGE * 100:.0f} points above the base rate. "
            "Items without a signal are not listed."
        ),
    )
