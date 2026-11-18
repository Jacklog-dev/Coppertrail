"""Pattern 5: buyout and reset, quantity drops abruptly while min buyout jumps, per snapshot."""

from __future__ import annotations

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, events_frame, pattern
from coppertrail.patterns.common import by_hour, duration, finish_ranked, minutes, pct

QTY_DROP = 0.40  # quantity down at least 40 % from the previous snapshot
MIN_JUMP = 0.20  # and min buyout up at least 20 %
# One snapshot an hour, a few seconds early or late; across a missed one (2 h) no compare.
MAX_GAP = pd.Timedelta(minutes=90)
MIN_PREV_QTY = 10  # tiny markets flip on one auction
RESET_BAND = 0.10  # reset: min back within 10 % of the pre-buyout min

HIT_EVENTS = 2  # a hit repeats: at least two buyouts that reset

RANKED_COLS = [
    "buyouts",
    "median_quantity_drop",
    "median_min_jump",
    "median_minutes_to_reset",
    "reset_share",
    "sales_per_day",
]
EVENT_DETAIL_COLS = [
    "item_id",
    "at",
    "quantity_before",
    "quantity_after",
    "quantity_drop",
    "min_before",
    "min_after",
    "min_jump",
    "reset_at",
    "minutes_to_reset",
]


def find(scans: pd.DataFrame) -> pd.DataFrame:
    out = []
    for item_id, g in scans.sort_values(["item_id", "observed_at"]).groupby("item_id"):
        g = g.reset_index(drop=True)
        t = g["observed_at"]
        q = g["quantity"].astype("float64")
        m = g["min"].astype("float64")
        pq, pm = q.shift(), m.shift()
        flag = (
            (t - t.shift() <= MAX_GAP)
            & (pq >= MIN_PREV_QTY)
            & (q <= pq * (1 - QTY_DROP))
            & (m >= pm * (1 + MIN_JUMP))
        )
        flag = flag & ~flag.shift(fill_value=False)  # a buyout over several snapshots counts once
        for i in np.flatnonzero(flag.to_numpy()):
            before = pm.iloc[i]
            later = np.flatnonzero((m.iloc[i + 1 :] <= before * (1 + RESET_BAND)).to_numpy())
            reset_at = t.iloc[i + 1 + later[0]] if len(later) else pd.NaT
            out.append(
                {
                    "item_id": int(item_id),
                    "at": t.iloc[i],
                    "quantity_before": pq.iloc[i],
                    "quantity_after": q.iloc[i],
                    "quantity_drop": q.iloc[i] / pq.iloc[i] - 1,
                    "min_before": before,
                    "min_after": m.iloc[i],
                    "min_jump": m.iloc[i] / before - 1,
                    "reset_at": reset_at,
                }
            )
    df = pd.DataFrame(out, columns=EVENT_DETAIL_COLS[:-1])
    df["at"] = pd.to_datetime(df["at"], utc=True)
    df["reset_at"] = pd.to_datetime(df["reset_at"], utc=True)
    df["minutes_to_reset"] = minutes(df["reset_at"] - df["at"]).astype("float64")
    return df[EVENT_DETAIL_COLS]


@pattern(
    "buyouts",
    number=5,
    title="Buyout and reset",
    min_days=1,
    data=("hourly", "latest", "items"),
    method=(
        "Snapshot to snapshot (at most 90 min apart, previous quantity at least 10): quantity "
        "down 40 % or more while min buyout rises 20 % or more. Reset = first later "
        "snapshot with min back within 10 % of the pre-buyout min."
    ),
)
def buyouts(ctx: Context) -> PatternResult:
    s = ctx.hourly
    if s.empty:
        return PatternResult(events=events_frame(), note="No hourly data in the range.")
    ev = find(s)
    events = events_frame(
        {
            "item_id": r.item_id,
            "at": r.at,
            "type": "buyout",
            "detail": (
                f"quantity {pct(r.quantity_drop)}, min {pct(r.min_jump)}, "
                + (
                    f"reset after {duration(r.minutes_to_reset)}"
                    if np.isfinite(r.minutes_to_reset)
                    else "no reset yet"
                )
            ),
            "magnitude": r.min_jump,
        }
        for r in ev.itertuples()
    )
    if ev.empty:
        ranked = pd.DataFrame(columns=["item_id", "name", *RANKED_COLS])
        hits = 0
    else:
        per = ev.groupby("item_id").agg(
            buyouts=("min_jump", "size"),
            median_quantity_drop=("quantity_drop", "median"),
            median_min_jump=("min_jump", "median"),
            median_minutes_to_reset=("minutes_to_reset", "median"),
            reset_share=("reset_at", lambda c: float(c.notna().mean())),
        )
        per = per.sort_values(["buyouts", "median_min_jump"], ascending=False)
        done = ev[ev["reset_at"].notna()].groupby("item_id").size()
        hits = int((done >= HIT_EVENTS).sum())
        per["_hit"] = per.index.map(done).fillna(0) >= HIT_EVENTS
        per = per.sort_values("_hit", ascending=False, kind="stable")
        ranked = finish_ranked(per.reset_index(), ctx, RANKED_COLS)
    return PatternResult(
        ranked=ranked,
        charts={"events": ev, "by_hour": by_hour(ev)},
        events=events,
        items_checked=int(s["item_id"].nunique()),
        items_hit=hits,
        note=(
            f"{len(ev)} events in {ev['item_id'].nunique()} items. "
            f"Hit: at least {HIT_EVENTS} buyouts that reset."
        ),
    )
