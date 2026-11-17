"""Pattern 11: patch and build effects, price and supply 24 h after a build vs 24 h before.

The placebo is the same 24 h-vs-24 h change at the item's other anchors at the same
UTC hour of day (24 h steps from the build), which takes out the launch-phase drift.
Builds are few, so every result here is an anecdote, not a statistic.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.common import finish_ranked, pct
from coppertrail.query.groups import starter_groups

WINDOW_H = 24  # pre and post window length
MIN_ROWS = 12  # hourly rows needed on each side
MIN_ANCHORS = 2  # placebo anchors needed for a placebo median
EXCLUDE_H = 24  # placebo anchors this close to any build (inclusive) are skipped
MOVE = 0.10  # hit: |excess price change| of 10 % or more ...
NOISE_K = 3  # ... at least 3 robust SDs of the item's placebo changes, and beyond
# every placebo change (with k anchors that alone passes by chance in 1 of k + 1 items)
CHART_H = 72  # window chart: offsets -72..72 h, 100 = pre-window median

H = pd.Timedelta(hours=1)
RANKED_COLS = [
    "build",
    "published_at",
    "price_change",
    "supply_change",
    "placebo_price",
    "placebo_spread",
    "excess_price",
    "excess_supply",
    "builds_tested",
]
BUILDS_COLS = ["build_id", "version", "stage", "title", "published_at", "usable", "items"]
GROUPS_COLS = [
    "version",
    "published_at",
    "group",
    "items",
    "median_price_change",
    "median_excess_price",
    "median_supply_change",
    "median_excess_supply",
]
WINDOW_COLS = ["item_id", "version", "published_at", "offset_h", "price_idx", "supply_idx"]
EFFECT_COLS = [
    "item_id",
    "build_id",
    "version",
    "published_at",
    "price_change",
    "supply_change",
    "placebo_price",
    "placebo_supply",
    "placebo_spread",
    "placebo_max",
    "anchors",
]


def _ratio(post: np.ndarray, pre: np.ndarray) -> float:
    # Medians: a single fantasy-priced or empty hour would dominate a mean.
    a, b = float(np.nanmedian(pre)), float(np.nanmedian(post))
    return b / a - 1 if a > 0 else np.nan


class _Series:
    """One item's hourly min and quantity, sorted, for fast window slicing."""

    def __init__(self, g: pd.DataFrame):
        g = g.sort_values("hour")
        self.t = g["hour"].to_numpy(dtype="datetime64[ns]")
        self.p = g["min"].to_numpy(dtype="float64")
        self.q = g["quantity"].to_numpy(dtype="float64")

    def bounds(self, at: np.datetime64) -> tuple[int, int, int]:
        w = np.timedelta64(WINDOW_H, "h")
        return tuple(np.searchsorted(self.t, [at - w, at, at + w]))  # type: ignore[return-value]

    def change(self, at: np.datetime64) -> tuple[float, float] | None:
        """(price change, supply change) post vs pre, or None without 12 rows each side."""
        a, b, c = self.bounds(at)
        if b - a < MIN_ROWS or c - b < MIN_ROWS:
            return None
        return _ratio(self.p[b:c], self.p[a:b]), _ratio(self.q[b:c], self.q[a:b])

    def placebo(self, at: np.datetime64, builds: np.ndarray) -> tuple:
        """Over the other day-aligned anchors: (median price change, median supply change,
        robust SD and largest distance from the median of the price changes, anchors)."""
        if not len(self.t):
            return np.nan, np.nan, np.nan, np.nan, 0
        day = np.timedelta64(24, "h")
        k_lo = int(np.floor((self.t[0] - at) / day))
        k_hi = int(np.ceil((self.t[-1] - at) / day))
        near = np.timedelta64(EXCLUDE_H, "h")
        ps, qs = [], []
        for k in range(k_lo, k_hi + 1):
            anchor = at + k * day
            if k == 0 or np.any(np.abs(builds - anchor) <= near):
                continue
            ch = self.change(anchor)
            if ch is None or not np.isfinite(ch[0]):
                continue
            ps.append(ch[0])
            qs.append(ch[1])
        if len(ps) < MIN_ANCHORS:
            return np.nan, np.nan, np.nan, np.nan, len(ps)
        qs = [q for q in qs if np.isfinite(q)]
        med = float(np.median(ps))
        dev = np.abs(np.asarray(ps) - med)
        spread, top = 1.4826 * float(np.median(dev)), float(dev.max())
        return med, float(np.median(qs)) if qs else np.nan, spread, top, len(ps)

    def window(self, at: np.datetime64) -> pd.DataFrame:
        a, b, _ = self.bounds(at)
        span = np.timedelta64(CHART_H, "h")
        lo = np.searchsorted(self.t, at - span, side="left")
        hi = np.searchsorted(self.t, at + span, side="right")
        pre_p, pre_q = float(np.nanmedian(self.p[a:b])), float(np.nanmedian(self.q[a:b]))
        off = np.round((self.t[lo:hi] - at) / np.timedelta64(1, "h")).astype("int64")
        return pd.DataFrame(
            {
                "offset_h": off,
                "price_idx": 100 * self.p[lo:hi] / pre_p if pre_p > 0 else np.nan,
                "supply_idx": 100 * self.q[lo:hi] / pre_q if pre_q > 0 else np.nan,
            }
        )


def _builds(ctx: Context) -> pd.DataFrame:
    b = ctx.builds.copy()
    b["published_at"] = pd.to_datetime(b["published_at"], utc=True)
    return b.dropna(subset=["published_at"]).sort_values("published_at").reset_index(drop=True)


def _memberships(items: pd.DataFrame, ids: list[int]) -> dict[int, list[str]]:
    """item_id -> starter groups it matches, plus 'All'."""
    names = dict(zip(items["item_id"].astype(int), items["name"].astype(str), strict=False))
    groups = starter_groups()
    out = {}
    for i in ids:
        it = SimpleNamespace(item_id=int(i), name=names.get(int(i), str(i)))
        out[int(i)] = [g.name for g in groups if g.matches(it)] + ["All"]
    return out


def effects(ctx: Context) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(per item and build effects, builds chart, window chart)."""
    b = _builds(ctx)
    h = ctx.hourly
    series = {int(i): _Series(g) for i, g in h.groupby("item_id")} if len(h) else {}
    all_at = b["published_at"].dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")
    rows, windows, brows = [], [], []
    for bi, build in b.iterrows():
        at = all_at[bi]
        found = []
        for item_id, s in series.items():
            ch = s.change(at)
            if ch is None or not np.isfinite(ch[0]):
                continue
            pp, pq, spread, top, n = s.placebo(at, all_at)
            found.append(item_id)
            rows.append(
                {
                    "item_id": item_id,
                    "build_id": build["build_id"],
                    "version": build["version"],
                    "published_at": build["published_at"],
                    "price_change": ch[0],
                    "supply_change": ch[1],
                    "placebo_price": pp,
                    "placebo_supply": pq,
                    "placebo_spread": spread,
                    "placebo_max": top,
                    "anchors": n,
                }
            )
            w = s.window(at)
            w.insert(0, "published_at", build["published_at"])
            w.insert(0, "version", build["version"])
            w.insert(0, "item_id", item_id)
            windows.append(w)
        brows.append({**{c: build[c] for c in BUILDS_COLS[:5]}, "usable": bool(found)})
        brows[-1]["items"] = len(found)
    eff = pd.DataFrame(rows, columns=EFFECT_COLS)
    eff["excess_price"] = eff["price_change"] - eff["placebo_price"]
    eff["excess_supply"] = eff["supply_change"] - eff["placebo_supply"]
    builds = pd.DataFrame(brows, columns=BUILDS_COLS)
    win = pd.concat(windows, ignore_index=True) if windows else pd.DataFrame(columns=WINDOW_COLS)
    return eff, builds, win[WINDOW_COLS]


def group_medians(eff: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    if eff.empty:
        return pd.DataFrame(columns=GROUPS_COLS)
    member = _memberships(items, sorted(eff["item_id"].unique()))
    e = eff.assign(group=eff["item_id"].map(member)).explode("group")
    g = e.groupby(["published_at", "version", "group"], sort=False)
    out = g.agg(
        items=("item_id", "nunique"),
        median_price_change=("price_change", "median"),
        median_excess_price=("excess_price", "median"),
        median_supply_change=("supply_change", "median"),
        median_excess_supply=("excess_supply", "median"),
    ).reset_index()
    return out.sort_values(["published_at", "group"])[GROUPS_COLS].reset_index(drop=True)


def _note(builds: pd.DataFrame, eff: pd.DataFrame, n_items: int) -> str:
    total, usable = len(builds), int(builds["usable"].sum()) if len(builds) else 0
    if total == 0:
        return "No builds in the range; the collector fills the builds table from its next run."
    verb = "is" if usable == 1 else "are"
    head = (
        f"Only {usable} of {total} build{'s' if total != 1 else ''} in the range {verb} usable "
        f"({WINDOW_H} h of data on both sides); results are anecdotes, not statistics."
    )
    tested = eff["item_id"].nunique() if len(eff) else 0
    no_placebo = int(eff["placebo_price"].isna().sum()) if len(eff) else 0
    # Without any effect an item's build change beats all k placebo changes with chance
    # 1 / (k + 1); over its builds that gives the expected number of chance hits.
    chance = 0.0
    if len(eff):
        p = 1 / (eff["anchors"].where(eff["anchors"] >= MIN_ANCHORS) + 1)
        chance = float((1 - (1 - p.fillna(0)).groupby(eff["item_id"]).prod()).sum())
    return (
        f"{head} Change = median hourly min (quantity) in the {WINDOW_H} h after the build vs "
        f"the {WINDOW_H} h before, at least {MIN_ROWS} rows each side. Placebo = median of the "
        f"same change at other anchors in 24 h steps (same UTC hour), skipping anchors within "
        f"{EXCLUDE_H} h of a build, at least {MIN_ANCHORS} anchors; excess = change − placebo. "
        f"Hit: |excess price| {pct(MOVE)[1:]} or more and at least {NOISE_K} robust SDs "
        f"of the item's placebo changes, and beyond every one of them (that last rule alone "
        f"would pick about {chance:.0f} items by chance). {tested} of {n_items} items "
        f"had data around a usable build; {no_placebo} item-build pairs lack a placebo "
        "(excess n/a)."
    )


@pattern(
    "build_effects",
    number=11,
    title="Patch and build effects",
    min_days=1,
    data=("builds", "hourly", "items"),
    method=(
        "Per build and item: median hourly min and quantity in the 24 h after the build "
        "against the 24 h before. Excess = change minus the item's placebo (median "
        "24 h-vs-24 h change at the same hour of day on other days). Group view: median "
        "excess per starter group and over all items."
    ),
)
def build_effects(ctx: Context) -> PatternResult:
    eff, builds, win = effects(ctx)
    n_items = int(ctx.hourly["item_id"].nunique()) if len(ctx.hourly) else 0
    charts = {"builds": builds, "groups": group_medians(eff, ctx.items), "window": win}
    note = _note(builds, eff, n_items)
    if eff.empty:
        empty = pd.DataFrame(columns=["item_id", "name", *RANKED_COLS])
        return PatternResult(ranked=empty, charts=charts, items_checked=n_items, note=note)
    e = eff.assign(
        _abs=eff["excess_price"].abs(),
        _raw=eff["price_change"].abs(),
        builds_tested=eff.groupby("item_id")["build_id"].transform("size"),
        build=eff["version"],
    )
    hit = (
        (
            (e["_abs"] >= MOVE)
            & (e["_abs"] >= NOISE_K * e["placebo_spread"])
            & (e["_abs"] > e["placebo_max"])
        )
        .groupby(e["item_id"])
        .any()
    )
    best = (
        e.sort_values(["_abs", "_raw"], ascending=False, na_position="last")
        .drop_duplicates("item_id")
        .sort_values("_abs", ascending=False, na_position="last")
    )
    return PatternResult(
        ranked=finish_ranked(best, ctx, RANKED_COLS),
        charts=charts,
        items_checked=n_items,
        items_hit=int(hit.sum()),
        note=note,
    )
