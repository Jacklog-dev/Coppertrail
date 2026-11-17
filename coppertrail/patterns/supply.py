"""Pattern 4: supply shocks, quantity jumps against a rolling baseline, and the price lag."""

from __future__ import annotations

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, events_frame, pattern
from coppertrail.patterns.baseline import _full_hours
from coppertrail.patterns.common import finish_ranked, pct, runs

JUMP = 0.60  # quantity at least 60 % above the baseline
BASE_HOURS = 24  # baseline: median of the prior 24 h
BASE_MIN = 12
MAX_LAG = 12  # hours after the shock checked for a price reaction
PRICE_MOVE = 0.05  # a reaction counts from 5 %

RANKED_COLS = [
    "shocks",
    "median_jump",
    "median_price_change",
    "median_lag_hours",
    "price_followed_share",
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
        base_q = q.shift().rolling(BASE_HOURS, min_periods=BASE_MIN).median()
        base_m = m.shift().rolling(BASE_HOURS, min_periods=BASE_MIN).median()
        flag = (q >= base_q * (1 + JUMP)) & base_q.gt(0)
        rid = runs(flag)
        c, lag = _xcorr(g)
        xc.append({"item_id": int(item_id), "xcorr": c, "xcorr_lag_hours": lag})
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
                }
            )
    ev = pd.DataFrame(shocks, columns=EVENT_DETAIL_COLS)
    ev["at"] = pd.to_datetime(ev["at"], utc=True)
    resp = (
        pd.concat(responses, ignore_index=True)
        if responses
        else pd.DataFrame(columns=["lag", "price_change", "item_id", "at"])
    )
    return ev, resp, pd.DataFrame(xc, columns=["item_id", "xcorr", "xcorr_lag_hours"])


@pattern(
    "supply_shocks",
    number=4,
    title="Supply shocks",
    min_days=3,
    data=("hourly", "snapshot", "items"),
    method=(
        "Hourly quantity at least 60 % above the median of the prior 24 h; a run of such "
        "hours is one shock. Price response: min buyout 0 to 12 h after the shock against "
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
                f"supply {pct(r.jump)} against the 24 h median; "
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
    else:
        per = ev.groupby("item_id").agg(
            shocks=("jump", "size"),
            median_jump=("jump", "median"),
            median_price_change=("price_change", "median"),
            median_lag_hours=("lag_hours", "median"),
            price_followed_share=(
                "price_change",
                lambda s: float((s.abs() >= PRICE_MOVE).mean()),
            ),
        )
        per = per.join(xc.set_index("item_id"))
        per = per.assign(_abs=per["median_price_change"].abs()).sort_values(
            ["shocks", "_abs"], ascending=False
        )
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
        items_hit=int(ev["item_id"].nunique()),
        note=f"{len(ev)} shocks; a price move counts from {PRICE_MOVE:.0%}.".replace("%", " %"),
    )
