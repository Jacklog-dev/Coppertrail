"""Pattern 1: daily rhythm per item, with a nightly buy 22:00 / sell 07:00 backtest."""

from __future__ import annotations

import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.baseline import CUT, TZ, _full_hours, trim_mean
from coppertrail.patterns.common import finish_ranked

# Buy around 22:00, sell around 07:00. Single hours are spiky and the API has night
# gaps (whole archive hours missing), so each side is the mean over the hours present.
BUY_HOURS = (21, 22, 23)
SELL_HOURS = (7, 8, 9)
MIN_WINDOW_HOURS = 2  # of the 3 hours per window; one lone hour is too spiky
# Robustness (2026-11-18, Jack): mornings after a buy-out show the min of a few leftover
# listings (20x the evening price), and a 1 copper step on a 10 copper item is 10 %.
RESULT_CAP = 1.0  # nightly result counts at most +100 %; raw_result keeps the real value
MIN_BUY_COPPER = 100  # items whose median evening buy price is below 1 silver are not ranked
WINDOW = 25  # centred rolling mean, +/-12 h: the "daily mean" behind index 100
MIN_PERIODS = 12
HIT_WIN_RATE = 0.6
HIT_MIN_NIGHTS = 5

RANKED_COLS = [
    "wins",
    "nights",
    "win_rate",
    "avg_result",
    "median_result",
    "sales_per_day",
    "cheapest_hour",
    "dearest_hour",
    "confidence",
]


def confidence(nights: int, win_rate: float) -> str:
    if nights >= 20 and win_rate >= 0.75:
        return "high"
    if nights >= 7 and win_rate >= HIT_WIN_RATE:
        return "medium"
    return "low"


def _indexed(h: pd.DataFrame) -> pd.DataFrame:
    full = _full_hours(h[["item_id", "hour", "min", "p25", "quantity"]])
    g = full.groupby("item_id")
    for col in ("min", "p25", "quantity"):
        trend = g[col].transform(
            lambda s: s.rolling(WINDOW, center=True, min_periods=MIN_PERIODS).mean()
        )
        full[f"{col}_trend"] = trend
        full[f"{col}_idx"] = 100 * full[col] / trend
    # The usual price: a sell order above it is unlikely to fill in volume.
    full["min_usual"] = g["min"].transform(
        lambda s: s.rolling(WINDOW, center=True, min_periods=MIN_PERIODS).median()
    )
    local = full["hour"].dt.tz_convert(TZ)
    full["hod"] = local.dt.hour
    full["day"] = local.dt.tz_localize(None).dt.normalize()
    return full


def _window(full: pd.DataFrame, hours: tuple[int, ...], name: str) -> pd.DataFrame:
    """Mean min and trend over the `hours` present, per item and local day."""
    w = full[full["hod"].isin(hours) & full["min"].notna()]
    out = w.groupby(["item_id", "day"]).agg(
        n=("min", "size"),
        price=("min", "mean"),
        trend=("min_trend", "mean"),
        usual=("min_usual", "mean"),
    )
    out = out[out["n"] >= MIN_WINDOW_HOURS].drop(columns="n")
    return out.rename(
        columns={"price": name, "trend": f"{name}_trend", "usual": f"{name}_usual"}
    ).reset_index()


def _nights(full: pd.DataFrame) -> pd.DataFrame:
    buy = _window(full, BUY_HOURS, "buy").rename(columns={"day": "night"})
    sell = _window(full, SELL_HOURS, "sell")
    sell["night"] = sell.pop("day") - pd.Timedelta(days=1)
    df = buy.merge(sell, on=["item_id", "night"]).dropna()
    df = df[(df["buy"] > 0) & (df["buy_usual"] > 0)]
    # Sell at the morning min, but never above the usual price: a morning min after a
    # buy-out is the price of a few leftover listings, not one a sell order fills at.
    sell = df[["sell", "sell_usual"]].min(axis=1)
    # Detrend: what the sell price would be had the item's usual price not moved overnight.
    # The rolling median, not the mean: morning spikes would bend a mean.
    drift = df["sell_usual"] / df["buy_usual"]
    df["result"] = (sell * (1 - CUT) / (df["buy"] * drift) - 1).clip(upper=RESULT_CAP)
    df["raw_result"] = df["sell"] * (1 - CUT) / df["buy"] - 1
    df["won"] = df["result"] > 0
    df["night"] = df["night"].dt.date
    return df[["item_id", "night", "buy", "sell", "raw_result", "result", "won"]].reset_index(
        drop=True
    )


@pattern(
    "daily_rhythm",
    number=1,
    title="Daily rhythm",
    min_days=7,
    data=("hourly", "snapshot", "items"),
    method=(
        "Hourly min, p25 and quantity as an index (100 = the item's centred 25 h mean), "
        "by CET hour. Backtest: buy at the mean min 21:00-24:00, sell at the next "
        "morning's mean min 07:00-10:00 (hours present) after the 5 % cut, detrended "
        "by the overnight change of the usual price. The sell price never exceeds the "
        "usual price (centred 25 h median of min), nightly results are capped at +100 % "
        "and items under 1 silver are not ranked."
    ),
)
def daily_rhythm(ctx: Context) -> PatternResult:
    h = ctx.hourly
    if h.empty:
        return PatternResult(note="No hourly data in the range.")
    full = _indexed(h)
    profile = (
        full.groupby(["item_id", "hod"])[["min_idx", "p25_idx", "quantity_idx"]]
        .mean()
        .reset_index()
        .rename(columns={"hod": "hour"})
    )
    nights = _nights(full)
    items_checked = int(h["item_id"].nunique())
    if nights.empty:
        return PatternResult(
            charts={"nights": nights, "typical_day": profile},
            items_checked=items_checked,
            note="No complete 22:00/07:00 night pairs.",
        )

    buy_price = nights.groupby("item_id")["buy"].median()
    cheap = buy_price[buy_price < MIN_BUY_COPPER].index
    nights = nights[~nights["item_id"].isin(cheap)]
    if nights.empty:
        return PatternResult(
            charts={"nights": nights, "typical_day": profile},
            items_checked=items_checked,
            note=f"Every item is below the price floor of {MIN_BUY_COPPER} copper.",
        )
    per = nights.groupby("item_id").agg(
        wins=("won", "sum"),
        nights=("won", "size"),
        # 20 % trimmed: one spiky night must not carry the average (HANDOVER 5).
        avg_result=("result", lambda s: trim_mean(s, 0.2)),
        median_result=("result", "median"),
    )
    per["wins"] = per["wins"].astype("int64")
    per["win_rate"] = per["wins"] / per["nights"]
    prof = profile.dropna(subset=["min_idx"])
    per["cheapest_hour"] = prof.loc[prof.groupby("item_id")["min_idx"].idxmin()].set_index(
        "item_id"
    )["hour"]
    per["dearest_hour"] = prof.loc[prof.groupby("item_id")["min_idx"].idxmax()].set_index(
        "item_id"
    )["hour"]
    per["confidence"] = [
        confidence(n, w) for n, w in zip(per["nights"], per["win_rate"], strict=True)
    ]
    per["hit"] = (
        (per["median_result"] > 0)
        & (per["win_rate"] >= HIT_WIN_RATE)
        & (per["nights"] >= HIT_MIN_NIGHTS)
    )
    order = {"high": 0, "medium": 1, "low": 2}
    per = per.assign(
        _c=per["confidence"].map(order), _few=per["nights"] < HIT_MIN_NIGHTS
    ).sort_values(["_c", "_few", "median_result", "win_rate"], ascending=[True, True, False, False])
    ranked = finish_ranked(per.reset_index(), ctx, RANKED_COLS)

    market = []
    for hour, g in profile.groupby("hour"):
        market.append(
            {
                "hour": int(hour),
                "min_idx": trim_mean(g["min_idx"]),
                "p25_idx": trim_mean(g["p25_idx"]),
                "quantity_idx": trim_mean(g["quantity_idx"]),
            }
        )
    most = int(per["nights"].max())
    return PatternResult(
        ranked=ranked,
        charts={
            "nights": nights,
            "typical_day": profile,
            "market_day": pd.DataFrame(market),
        },
        items_checked=items_checked,
        items_hit=int(per["hit"].sum()),
        note=(
            f"Hit: median night > 0, at least {HIT_WIN_RATE:.0%} of nights won and "
            f"{HIT_MIN_NIGHTS} nights tested. "
            f"Robust: each window needs {MIN_WINDOW_HOURS} of its 3 hours, a night counts "
            f"at most +{RESULT_CAP:.0%}, and {len(cheap)} item{'' if len(cheap) == 1 else 's'} "
            f"below the price floor of {MIN_BUY_COPPER} copper (median evening buy) "
            f"{'is' if len(cheap) == 1 else 'are'} not ranked. "
            f"At most {most} nights per item, so confidence stays "
            f"{'medium or lower' if most < 20 else 'as labelled'}; "
            "no weekday effects are claimed."
        ).replace("%", " %"),
    )
