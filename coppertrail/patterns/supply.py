"""Pattern 4: supply shocks, quantity jumps against a rolling baseline, and the price lag."""

from __future__ import annotations

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, events_frame, pattern
from coppertrail.patterns.baseline import _full_hours
from coppertrail.patterns.common import finish_ranked, pct, runs

JUMP = 1.0  # quantity at least double the baseline
BASE_HOURS = 24  # baseline: median of the prior 24 h, but at least the same hours yesterday
BASE_MIN = 12
MIN_BASE_QTY = 20  # thinner markets double on a single seller
MIN_RUN = 2  # the jump lasts two hours or more
HIT_SHOCKS = 2
HIT_FELL_SHARE = 0.5
HIT_EXCESS = 0.25  # and 25 points more often than after any hour
MAX_LAG = 12  # hours after the shock checked for a price reaction
PRICE_MOVE = 0.10  # a reaction counts from a 10 % move

RANKED_COLS = [
    "shocks",
    "median_jump",
    "median_price_change",
    "median_lag_hours",
    "price_fell_share",
    "base_fell_share",
    "xcorr",
    "xcorr_lag_hours",
    "sales_per_day",
]
EVENT_DETAIL_COLS = [
    "item_id",
    "at",
    "quantity",
    "baseline",
    "jump",
    "hours",
    "price_change",
    "lag_hours",
    "price_fell",
]


def _xcorr(g: pd.DataFrame) -> tuple[float, int]:
    """Lag (hours, quantity leading price when > 0) with the strongest correlation."""
    dq = np.log(g["quantity"].where(g["quantity"] > 0)).diff()
    dm = np.log(g["min"].where(g["min"] > 0)).diff()
    best = (np.nan, 0)
    for lag in range(-MAX_LAG, MAX_LAG + 1):
        c = dq.corr(dm.shift(-lag))
        if np.isfinite(c) and (not np.isfinite(best[0]) or abs(c) > abs(best[0])):
            best = (float(c), lag)
    return best


def find(h: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Shocks, per-shock price response by lag, and per-item cross-correlation."""
    full = _full_hours(h[["item_id", "hour", "min", "quantity"]])
    shocks, responses, xc = [], [], []
    for item_id, g in full.groupby("item_id"):
        g = g.reset_index(drop=True)
        q = g["quantity"].astype("float64")
        m = g["min"].astype("float64")
        median_q = q.shift().rolling(BASE_HOURS, min_periods=BASE_MIN).median()
        # The same hours yesterday (+/-1 h) keep the daily rhythm from counting as a shock.
        yesterday = q.shift(24).rolling(3, center=True, min_periods=1).max()
        base_q = np.fmax(median_q, yesterday)
        base_m = m.shift().rolling(BASE_HOURS, min_periods=BASE_MIN).median()
        # Without yesterday's hours the rhythm can't be told apart: no shock on day one.
        flag = (q >= base_q * (1 + JUMP)) & (median_q >= MIN_BASE_QTY) & yesterday.notna()
        rid = runs(flag)
        lengths = rid[rid >= 0].value_counts()
        rid = rid.where(rid.map(lengths).fillna(0) >= MIN_RUN, -1)
        c, lag = _xcorr(g)
        # How often min dips that far within 12 h after any hour: the base rate to beat.
        ahead = m[::-1].rolling(MAX_LAG + 1, min_periods=1).min()[::-1]
        dipped = (ahead <= base_m * (1 - PRICE_MOVE))[base_m.notna() & m.notna()]
        base_rate = float(dipped.mean()) if len(dipped) else np.nan
        xc.append(
            {
                "item_id": int(item_id),
                "xcorr": c,
                "xcorr_lag_hours": lag,
                "base_fell_share": base_rate,
            }
        )
        for r in sorted(set(rid) - {-1}):
            idx = np.flatnonzero(rid.to_numpy() == r)
            i = idx[0]
            ref = base_m.iloc[i]
            window = m.iloc[i : i + MAX_LAG + 1].to_numpy() / ref - 1
            resp = pd.DataFrame({"lag": np.arange(len(window)), "price_change": window})
            resp["item_id"] = int(item_id)
            resp["at"] = g["hour"].iloc[i]
            responses.append(resp)
            valid = resp.dropna()
            if valid.empty or not np.isfinite(ref):
                change, best_lag = np.nan, np.nan
            else:
                k = valid["price_change"].abs().idxmax()
                change, best_lag = valid.loc[k, "price_change"], valid.loc[k, "lag"]
            shocks.append(
                {
                    "item_id": int(item_id),
                    "at": g["hour"].iloc[i],
                    "quantity": float(q.iloc[idx].max()),
                    "baseline": float(base_q.iloc[i]),
                    "jump": float(q.iloc[idx].max() / base_q.iloc[i] - 1),
                    "hours": len(idx),
                    "price_change": change,
                    "lag_hours": best_lag,
                    "price_fell": bool((valid["price_change"] <= -PRICE_MOVE).any()),
                }
            )
    ev = pd.DataFrame(shocks, columns=EVENT_DETAIL_COLS)
    ev["at"] = pd.to_datetime(ev["at"], utc=True)
    resp = (
        pd.concat(responses, ignore_index=True)
        if responses
        else pd.DataFrame(columns=["lag", "price_change", "item_id", "at"])
    )
    cols = ["item_id", "xcorr", "xcorr_lag_hours", "base_fell_share"]
    return ev, resp, pd.DataFrame(xc, columns=cols)


@pattern(
    "supply_shocks",
    number=4,
    title="Supply shocks",
    min_days=3,
    data=("hourly", "snapshot", "items"),
    method=(
        "Hourly quantity at least double its baseline (the prior 24 h median, but at "
        "least the same hours yesterday) for 2 h or more, baseline 20 units at least; "
        "one run is one shock. Price response: min buyout 0 to 12 h after the shock against "
        "its prior 24 h median, the lag with the largest move. Lead/lag: correlation of "
        "hourly log changes of quantity and min over lags -12..12 h."
    ),
)
def supply_shocks(ctx: Context) -> PatternResult:
    h = ctx.hourly
    if h.empty:
        return PatternResult(events=events_frame(), note="No hourly data in the range.")
    ev, resp, xc = find(h)
    events = events_frame(
        {
            "item_id": r.item_id,
            "at": r.at,
            "type": "supply_shock",
            "detail": (
                f"supply {pct(r.jump)} against its baseline; "
                + (
                    f"min {pct(r.price_change)} after {int(r.lag_hours)} h"
                    if np.isfinite(r.price_change)
                    else "no price data after it"
                )
            ),
            "magnitude": r.jump,
        }
        for r in ev.itertuples()
    )
    if ev.empty:
        ranked = pd.DataFrame(columns=["item_id", "name", *RANKED_COLS])
        resp_all = pd.DataFrame(columns=["lag", "price_change", "shocks"])
        hits = 0
    else:
        per = ev.groupby("item_id").agg(
            shocks=("jump", "size"),
            median_jump=("jump", "median"),
            median_price_change=("price_change", "median"),
            median_lag_hours=("lag_hours", "median"),
            price_fell_share=("price_fell", "mean"),
        )
        per = per.join(xc.set_index("item_id"))
        per["hit"] = (
            (per["shocks"] >= HIT_SHOCKS)
            & (per["price_fell_share"] >= HIT_FELL_SHARE)
            & (per["price_fell_share"] >= per["base_fell_share"] + HIT_EXCESS)
        )
        per = per.sort_values(["hit", "price_fell_share", "shocks"], ascending=False)
        hits = int(per["hit"].sum())
        ranked = finish_ranked(per.reset_index(), ctx, RANKED_COLS)
        resp_all = (
            resp.groupby("lag")
            .agg(price_change=("price_change", "median"), shocks=("price_change", "count"))
            .reset_index()
        )
    per_item_resp = (
        resp.groupby(["item_id", "lag"])["price_change"].median().reset_index()
        if len(resp)
        else pd.DataFrame(columns=["item_id", "lag", "price_change"])
    )
    return PatternResult(
        ranked=ranked,
        charts={"events": ev, "response": per_item_resp, "response_all": resp_all, "xcorr": xc},
        events=events,
        items_checked=int(h["item_id"].nunique()),
        items_hit=hits,
        note=(
            f"{len(ev)} shocks in {ev['item_id'].nunique()} items. Hit: {HIT_SHOCKS} shocks "
            f"or more and min down {PRICE_MOVE:.0%} or more within 12 h after at least "
            f"half of them, {HIT_EXCESS:.0%} points more often than after any hour."
        ).replace("%", " %"),
    )
