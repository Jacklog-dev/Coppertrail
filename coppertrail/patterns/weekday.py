"""Pattern 2: weekday profile per item and the weekly raid reset effect.

Assumption (unverified for WoW Forever): the EU weekly reset is Wednesday 04:00 UTC
(05:00 CET in winter), as on EU Classic realms. If the realm resets at another time,
change RESET_WEEKDAY / RESET_HOUR_UTC.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.baseline import trim_mean
from coppertrail.patterns.common import daily_prices, finish_ranked

RESET_WEEKDAY = 2  # Wednesday (0 = Monday), UTC; assumption, see module docstring
RESET_HOUR_UTC = 4
WINDOW = 7  # centred rolling mean over 7 days: each weekday exactly once
RESET_SIDE = pd.Timedelta(hours=24)
RESET_MIN_ROWS = 12  # hourly rows needed on each side of a reset instant
HIT_AMPLITUDE = 0.08
HIT_CONSISTENCY = 0.75
HIT_MIN_WEEKS = 3
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

RANKED_COLS = [
    "weeks",
    "peak_day",
    "trough_day",
    "amplitude",
    "consistency",
    "supply_amplitude",
    "reset_change",
    "resets",
]
DAILY_COLS = ["item_id", "day", "weekday", "week", "price_idx", "supply_idx"]
WEEKDAY_COLS = ["item_id", "weekday", "day_name", "price_idx", "supply_idx"]
MARKET_COLS = ["weekday", "day_name", "price_idx", "supply_idx", "items"]
RESET_COLS = ["item_id", "reset_at", "change", "placebo"]


def daily_index(h: pd.DataFrame) -> pd.DataFrame:
    """Per item and CET day: price and quantity as 100 x value / centred 7-day mean."""
    d = daily_prices(h)
    if d.empty:
        return pd.DataFrame(columns=DAILY_COLS)
    if "quantity" not in d:
        d["quantity"] = np.nan
    out = []
    for item_id, g in d.groupby("item_id"):
        g = g.set_index(pd.to_datetime(g["day"]))[["price", "quantity"]].astype("float64")
        g = g.reindex(pd.date_range(g.index.min(), g.index.max(), freq="D"))
        roll = g.rolling(WINDOW, center=True, min_periods=WINDOW).mean()
        idx = 100 * g / roll
        out.append(
            pd.DataFrame(
                {
                    "item_id": int(item_id),
                    "day": idx.index.date,
                    "weekday": idx.index.day_of_week,
                    "week": (idx.index - pd.to_timedelta(idx.index.day_of_week, unit="D")).date,
                    "price_idx": idx["price"].to_numpy(),
                    "supply_idx": idx["quantity"].to_numpy(),
                }
            )
        )
    df = pd.concat(out, ignore_index=True)
    return df.dropna(subset=["price_idx"]).reset_index(drop=True)[DAILY_COLS]


def weekday_stats(daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per item and weekday profile, per item summary)."""
    prof = daily.groupby(["item_id", "weekday"])[["price_idx", "supply_idx"]].mean().reset_index()
    prof["day_name"] = prof["weekday"].map(dict(enumerate(DAY_NAMES)))
    rows = []
    for item_id, p in prof.groupby("item_id"):
        dd = daily[daily["item_id"] == item_id]
        peak = int(p.loc[p["price_idx"].idxmax(), "weekday"])
        trough = int(p.loc[p["price_idx"].idxmin(), "weekday"])
        week_mean = dd.groupby("week")["price_idx"].mean()
        at_peak = dd[dd["weekday"] == peak].set_index("week")["price_idx"]
        above = at_peak > week_mean.reindex(at_peak.index)
        supply = p["supply_idx"].dropna()
        rows.append(
            {
                "item_id": int(item_id),
                "weeks": int(dd["week"].nunique()),
                "peak_day": DAY_NAMES[peak],
                "trough_day": DAY_NAMES[trough],
                "amplitude": (p["price_idx"].max() - p["price_idx"].min()) / 100,
                "consistency": float(above.mean()) if len(above) else np.nan,
                "supply_amplitude": (supply.max() - supply.min()) / 100 if len(supply) else np.nan,
            }
        )
    return prof[WEEKDAY_COLS], pd.DataFrame(rows)


def _changes(ts: np.ndarray, v: np.ndarray, instants: pd.DatetimeIndex) -> np.ndarray:
    """Mean of the 24 h after each instant over the mean of the 24 h before, minus 1."""
    c = np.concatenate([[0.0], np.cumsum(v)])
    t = instants.as_unit("ns").asi8
    side = RESET_SIDE.value
    lo, mid, hi = (np.searchsorted(ts, x, side="left") for x in (t - side, t, t + side))
    n_before, n_after = mid - lo, hi - mid
    with np.errstate(divide="ignore", invalid="ignore"):
        before = (c[mid] - c[lo]) / n_before
        after = (c[hi] - c[mid]) / n_after
        out = after / before - 1
    ok = (n_before >= RESET_MIN_ROWS) & (n_after >= RESET_MIN_ROWS) & (before > 0)
    return np.where(ok, out, np.nan)


def reset_effect(h: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per item and reset: change and placebo, per item: reset_change and resets)."""
    h = h.dropna(subset=["min"])
    if h.empty:
        return pd.DataFrame(columns=RESET_COLS), pd.DataFrame(
            columns=["item_id", "reset_change", "resets"]
        )
    first = h["hour"].min().floor("D") + pd.Timedelta(hours=RESET_HOUR_UTC)
    instants = pd.date_range(first, h["hour"].max(), freq="D")
    since = (instants.day_of_week - RESET_WEEKDAY) % 7
    is_reset = since == 0
    # Placebo days whose 24 h windows touch a reset window (the days before and after) would
    # carry part of the reset effect; leave them out.
    is_placebo = (since != 1) & (since != 6) & ~is_reset
    chart, summary = [], []
    for item_id, g in h.sort_values("hour").groupby("item_id"):
        ch = _changes(
            pd.DatetimeIndex(g["hour"]).as_unit("ns").asi8,
            g["min"].to_numpy(dtype="float64"),
            instants,
        )
        reset = pd.Series(ch[is_reset], index=instants[is_reset]).dropna()
        placebo = pd.Series(ch[is_placebo]).dropna()
        if reset.empty:
            continue
        base = float(placebo.median()) if len(placebo) else np.nan
        summary.append(
            {
                "item_id": int(item_id),
                "reset_change": float(reset.median()) - base,
                "resets": len(reset),
            }
        )
        chart.append(
            pd.DataFrame(
                {"item_id": int(item_id), "reset_at": reset.index, "change": reset.values}
            ).assign(placebo=base)
        )
    chart_df = pd.concat(chart, ignore_index=True) if chart else pd.DataFrame(columns=RESET_COLS)
    summ = pd.DataFrame(summary, columns=["item_id", "reset_change", "resets"])
    return chart_df[RESET_COLS], summ


def market_profile(prof: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "weekday": int(wd),
            "day_name": DAY_NAMES[int(wd)],
            "price_idx": trim_mean(g["price_idx"]),
            "supply_idx": trim_mean(g["supply_idx"]),
            "items": int(g["price_idx"].notna().sum()),
        }
        for wd, g in prof.groupby("weekday")
    ]
    return pd.DataFrame(rows, columns=MARKET_COLS)


def _empty(note: str, items_checked: int = 0) -> PatternResult:
    return PatternResult(
        ranked=pd.DataFrame(columns=["item_id", "name", *RANKED_COLS]),
        charts={
            "weekday": pd.DataFrame(columns=WEEKDAY_COLS),
            "market_weekday": pd.DataFrame(columns=MARKET_COLS),
            "reset": pd.DataFrame(columns=RESET_COLS),
        },
        items_checked=items_checked,
        note=note,
    )


@pattern(
    "weekday_reset",
    number=2,
    title="Weekday and raid reset",
    min_days=28,
    data=("hourly", "snapshot", "items"),
    method=(
        "Daily price = CET-day median of hourly min, supply = mean quantity; each divided "
        "by its centred 7-day mean (index 100, each weekday once in the window) and "
        "averaged per weekday. Amplitude = max - min of the weekday price index; "
        "consistency = share of weeks whose peak-weekday index is above that week's mean. "
        "Reset change = median over resets of the 24 h mean min after against the 24 h "
        "before, minus the same median at 04:00 UTC on days not next to a reset. Assumption, "
        "unverified for WoW Forever: the weekly reset is Wednesday 04:00 UTC (05:00 CET), "
        "as on EU Classic realms."
    ),
)
def weekday_reset(ctx: Context) -> PatternResult:
    h = ctx.hourly
    if h.empty:
        return _empty("No hourly data in the range.")
    items_checked = int(h["item_id"].nunique())
    daily = daily_index(h)
    if daily.empty:
        return _empty("No item has 7 consecutive priced days.", items_checked)
    prof, per = weekday_stats(daily)
    reset_chart, reset = reset_effect(h)
    per = per.merge(reset, on="item_id", how="left")
    per["resets"] = per["resets"].fillna(0).astype("int64")
    per["hit"] = (
        (per["amplitude"] >= HIT_AMPLITUDE)
        & (per["consistency"] >= HIT_CONSISTENCY)
        & (per["weeks"] >= HIT_MIN_WEEKS)
    )
    per = (
        per.assign(_score=per["amplitude"] * per["consistency"])
        .sort_values("_score", ascending=False, na_position="last")
        .drop(columns="_score")
    )
    skipped = items_checked - len(per)
    return PatternResult(
        ranked=finish_ranked(per, ctx, RANKED_COLS),
        charts={
            "weekday": prof,
            "market_weekday": market_profile(prof),
            "reset": reset_chart,
        },
        items_checked=items_checked,
        items_hit=int(per["hit"].sum()),
        note=(
            f"Hit: amplitude {HIT_AMPLITUDE:.0%} or more, peak weekday above the week's "
            f"mean in {HIT_CONSISTENCY:.0%} of weeks, at least {HIT_MIN_WEEKS} weeks. "
            f"{skipped} items skipped (no 7 consecutive priced days). Reset windows need "
            f"{RESET_MIN_ROWS} hourly rows on each side; reset time Wednesday "
            f"{RESET_HOUR_UTC:02d}:00 UTC is an unverified assumption."
        ).replace("%", " %"),
    )
