"""Pattern 3: mispricings (snipes), min buyout far below a rolling p25, per scan."""

from __future__ import annotations

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, events_frame, pattern
from coppertrail.patterns.common import by_hour, duration, finish_ranked, minutes, pct, runs

THRESHOLD = 0.30  # min buyout at least 30 % below the reference
REF_WINDOW = "6h"  # reference: median of p25 over the prior 6 h of scans
REF_MIN_SCANS = 6
MAX_GAP = pd.Timedelta(minutes=60)  # a later scan further away says nothing about the fix

HIT_EVENTS = 2  # a hit repeats: at least two mispricings that corrected

RANKED_COLS = [
    "events",
    "median_depth",
    "deepest",
    "median_minutes_to_correct",
    "corrected_share",
    "sales_per_day",
]
EVENT_DETAIL_COLS = [
    "item_id",
    "at",
    "min",
    "reference",
    "depth",
    "scans",
    "corrected_at",
    "minutes_to_correct",
]


def _reference(g: pd.DataFrame) -> pd.Series:
    s = g.set_index("observed_at")["p25"].astype("float64")
    ref = s.rolling(REF_WINDOW, closed="left", min_periods=REF_MIN_SCANS).median()
    return pd.Series(ref.to_numpy(), index=g.index)


def find(scans: pd.DataFrame, threshold: float = THRESHOLD) -> pd.DataFrame:
    """One row per mispricing: a run of consecutive scans below the threshold line."""
    out = []
    for item_id, g in scans.sort_values(["item_id", "observed_at"]).groupby("item_id"):
        g = g.reset_index(drop=True)
        ref = _reference(g)
        line = ref * (1 - threshold)
        flag = (g["min"] < line) & ref.notna()
        rid = runs(flag)
        for r in sorted(set(rid) - {-1}):
            idx = np.flatnonzero(rid.to_numpy() == r)
            first, last = idx[0], idx[-1]
            reference = float(ref.iloc[first])
            low = float(g["min"].iloc[idx].min())
            after = last + 1
            corrected_at = pd.NaT
            if (
                after < len(g)
                and g["observed_at"].iloc[after] - g["observed_at"].iloc[last] <= MAX_GAP
            ):
                corrected_at = g["observed_at"].iloc[after]
            out.append(
                {
                    "item_id": int(item_id),
                    "at": g["observed_at"].iloc[first],
                    "min": low,
                    "reference": reference,
                    "depth": low / reference - 1,
                    "scans": len(idx),
                    "corrected_at": corrected_at,
                }
            )
    df = pd.DataFrame(out, columns=EVENT_DETAIL_COLS[:-1])
    df["at"] = pd.to_datetime(df["at"], utc=True)
    df["corrected_at"] = pd.to_datetime(df["corrected_at"], utc=True)
    df["minutes_to_correct"] = minutes(df["corrected_at"] - df["at"]).astype("float64")
    return df[EVENT_DETAIL_COLS]


@pattern(
    "mispricings",
    number=3,
    title="Mispricings",
    min_days=1,
    data=("scans", "snapshot", "items"),
    method=(
        "Per scan: min buyout at least 30 % below the median p25 of the prior 6 h "
        "(6 scans at least). Consecutive scans below that line are one event; it "
        "corrects at the first later scan back above the line."
    ),
)
def mispricings(ctx: Context) -> PatternResult:
    s = ctx.scans
    if s.empty:
        return PatternResult(events=events_frame(), note="No scan data in the range.")
    ev = find(s)
    checked = int(s["item_id"].nunique())
    events = events_frame(
        {
            "item_id": r.item_id,
            "at": r.at,
            "type": "mispricing",
            "detail": (
                f"min {pct(r.depth)} below the rolling p25, "
                + (
                    f"back after {duration(r.minutes_to_correct)}"
                    if np.isfinite(r.minutes_to_correct)
                    else "not corrected yet"
                )
            ),
            "magnitude": r.depth,
        }
        for r in ev.itertuples()
    )
    if ev.empty:
        ranked = pd.DataFrame(columns=["item_id", "name", *RANKED_COLS])
        hits = 0
    else:
        per = ev.groupby("item_id").agg(
            events=("depth", "size"),
            median_depth=("depth", "median"),
            deepest=("depth", "min"),
            median_minutes_to_correct=("minutes_to_correct", "median"),
            corrected_share=("corrected_at", lambda c: float(c.notna().mean())),
        )
        per = per.sort_values(["events", "median_depth"], ascending=[False, True])
        done = ev[ev["corrected_at"].notna()].groupby("item_id").size()
        hits = int((done >= HIT_EVENTS).sum())
        per["_hit"] = per.index.map(done).fillna(0) >= HIT_EVENTS
        per = per.sort_values("_hit", ascending=False, kind="stable")
        ranked = finish_ranked(per.reset_index(), ctx, RANKED_COLS)
    return PatternResult(
        ranked=ranked,
        charts={"events": ev, "by_hour": by_hour(ev)},
        events=events,
        items_checked=checked,
        items_hit=hits,
        note=(
            f"{len(ev)} events in {ev['item_id'].nunique()} items. "
            f"Hit: at least {HIT_EVENTS} mispricings that corrected."
        ),
    )
