"""Pattern 9: correlated items (HANDOVER section 6), lagged correlation of residual returns.

Daily price = CET-day median of hourly min. Items priced on at least 80 % of the days,
top 200 by turnover. Return = daily log change minus the market's median log change
that day (takes out market-wide moves), demeaned per item. For every pair and lag
-3..3 days the Pearson correlation over the overlapping days (at least 14); the best
lag per pair by absolute correlation. One row per pair, `item_id` = the leader.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context, PatternResult, pattern
from coppertrail.patterns.common import daily_prices, finish_ranked, names
from coppertrail.query.groups import starter_groups

MAX_ITEMS = 200
MIN_COVERAGE = 0.8  # share of days an item must be priced on
LAGS = range(-3, 4)
MAX_LAG = 3
MIN_OVERLAP = 14
THRESHOLD = 0.6
TOP = 100

RANKED_COLS = [
    "partner_id",
    "partner_name",
    "lag_days",
    "corr",
    "n_days",
    "same_group",
    "hit",
    "sales_per_day",
]
SERIES_COLS = ["item_id", "day", "price", "resid"]
LAG_COLS = ["item_id", "partner_id", "lag", "corr", "n"]


def residuals(wide: pd.DataFrame) -> pd.DataFrame:
    """day x item prices -> day x item residual log returns (NaN where a day is missing)."""
    ret = np.log(wide).diff()
    market = ret.median(axis=1, skipna=True)
    resid = ret.sub(market, axis=0)
    return resid - resid.mean()


def lag_corr(r: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """(corr, n) matrices: [i, j] = corr(r_i[t], r_j[t + lag]) over shared days, lag >= 0."""
    t = r.shape[0]
    x, y = r[: t - lag], r[lag:]
    mx, my = ~np.isnan(x), ~np.isnan(y)
    x0, y0 = np.where(mx, x, 0.0), np.where(my, y, 0.0)
    fx, fy = mx.astype(float), my.astype(float)
    n = fx.T @ fy
    sx, sy = x0.T @ fy, fx.T @ y0
    sxx, syy = (x0**2).T @ fy, fx.T @ (y0**2)
    sxy = x0.T @ y0
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = n * sxy - sx * sy
        var = (n * sxx - sx**2) * (n * syy - sy**2)
        c = np.where((n >= MIN_OVERLAP) & (var > 0), cov / np.sqrt(var), np.nan)
    return np.clip(c, -1, 1), n


def chance_pairs(pairs: int, n: float) -> float:
    """Expected pairs with |r| >= THRESHOLD under no correlation (Fisher z, normal approx)."""
    if pairs == 0 or not np.isfinite(n) or n <= 3:
        return 0.0
    z = math.atanh(THRESHOLD) * math.sqrt(n - 3)
    p = 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return pairs * min(1.0, p * len(LAGS))


def group_sets(items: pd.DataFrame) -> dict[int, set[str]]:
    """item_id -> names of the starter groups it belongs to."""
    groups = starter_groups()
    out = {}
    for r in items.itertuples():
        it = SimpleNamespace(item_id=int(r.item_id), name=str(r.name))
        out[it.item_id] = {g.name for g in groups if g.matches(it)}
    return out


def _empty(note: str, checked: int = 0) -> PatternResult:
    return PatternResult(
        ranked=pd.DataFrame(columns=["item_id", "name", *RANKED_COLS]),
        charts={
            "series": pd.DataFrame(columns=SERIES_COLS),
            "lags": pd.DataFrame(columns=LAG_COLS),
        },
        items_checked=checked,
        note=note,
    )


@pattern(
    "correlations",
    number=9,
    title="Correlated items",
    min_days=21,
    data=("hourly", "latest", "items"),
    method=(
        "Daily price = CET-day median of hourly min. Items priced on 80 % of the days or "
        "more, top 200 by turnover (sales/day x min buyout). Residual return = daily log "
        "change minus the market's median log change that day, demeaned per item. "
        "Pearson correlation per pair for lags -3..3 days on 14+ overlapping days; best "
        "lag by absolute correlation, positive lag = partner follows the item."
    ),
)
def correlations(ctx: Context) -> PatternResult:
    d = daily_prices(ctx.hourly)
    d = d[d["price"] > 0]
    if d.empty:
        return _empty("No daily prices in the range.")
    wide = d.pivot(index="day", columns="item_id", values="price").sort_index()
    coverage = wide.notna().mean()
    sparse = int((coverage < MIN_COVERAGE).sum())
    wide = wide.loc[:, coverage >= MIN_COVERAGE]
    snap = ctx.latest
    turnover = (
        (snap["sales_per_day"].astype(float) * snap["min_buyout"].astype(float))
        .groupby(snap["item_id"])
        .max()
    )
    # Items without a latest row rank last.
    t = turnover.reindex(wide.columns).fillna(-np.inf)
    wide = wide[sorted(t.sort_values(ascending=False, kind="stable").index[:MAX_ITEMS])]
    ids = np.asarray(wide.columns, dtype="int64")
    skip = f" {sparse} items priced on fewer than 80 % of the days were skipped." if sparse else ""
    if len(ids) < 2:
        return _empty(f"Fewer than two items with enough daily prices.{skip}", len(ids))

    resid = residuals(wide)
    r = resid.to_numpy(dtype=float)
    mats = {lag: lag_corr(r, lag) for lag in range(MAX_LAG + 1)}

    # Stack lags -3..3 for the upper triangle a < b.
    ia, ib = np.triu_indices(len(ids), k=1)
    cells = [cell(mats, ia, ib, lag) for lag in LAGS]
    cs, ns = np.stack([c for c, _ in cells]), np.stack([n for _, n in cells])
    valid = ~np.isnan(cs)
    tested = valid.any(axis=0)
    pairs = int(tested.sum())
    if pairs == 0:
        return _empty(f"No pair has {MIN_OVERLAP} overlapping days.{skip}", len(ids))
    best = np.nanargmax(np.where(valid, np.abs(cs), -1), axis=0)
    cols = np.arange(len(ia))
    bc, bn = cs[best, cols], ns[best, cols]
    blag = np.asarray(list(LAGS))[best]
    lead = np.where(blag >= 0, ia, ib)[tested]
    follow = np.where(blag >= 0, ib, ia)[tested]
    pairs_df = pd.DataFrame(
        {
            "li": lead,
            "fi": follow,
            "item_id": ids[lead],
            "partner_id": ids[follow],
            "lag_days": np.abs(blag[tested]).astype("int64"),
            "corr": bc[tested],
            "n_days": bn[tested].astype("int64"),
        }
    )
    pairs_df["hit"] = pairs_df["corr"].abs() >= THRESHOLD
    pairs_df = pairs_df.sort_values("corr", key=np.abs, ascending=False, kind="stable")
    n_hits = int(pairs_df["hit"].sum())
    top = pairs_df.head(max(TOP, n_hits)).copy()

    gs = group_sets(ctx.items)
    top["same_group"] = [
        bool(gs.get(a, set()) & gs.get(b, set()))
        for a, b in zip(top["item_id"], top["partner_id"], strict=True)
    ]
    nm = names(ctx).set_index("item_id")["name"]
    top["partner_name"] = top["partner_id"].map(nm).fillna(top["partner_id"].astype(str))
    ranked = finish_ranked(top, ctx, RANKED_COLS)

    lag_rows = []
    for li, fi, a, b in zip(top["li"], top["fi"], top["item_id"], top["partner_id"], strict=True):
        for lag in LAGS:
            c, n = cell(mats, li, fi, lag)
            lag_rows.append({"item_id": a, "partner_id": b, "lag": lag, "corr": c, "n": int(n)})
    lags = pd.DataFrame(lag_rows, columns=LAG_COLS)

    series = (
        wide.stack()
        .rename("price")
        .reset_index()
        .merge(resid.stack().rename("resid").reset_index(), on=["day", "item_id"], how="left")
    )[SERIES_COLS]

    hit_items = set(pairs_df.loc[pairs_df["hit"], "item_id"]) | set(
        pairs_df.loc[pairs_df["hit"], "partner_id"]
    )
    n_med = float(np.median(ns[valid]))
    chance = chance_pairs(pairs, n_med)
    return PatternResult(
        ranked=ranked,
        charts={"series": series, "lags": lags},
        items_checked=len(ids),
        items_hit=len(hit_items),
        note=(
            f"{pairs} pairs tested over lags -3..3, {n_hits} with |correlation| >= "
            f"{THRESHOLD:.1f} on {MIN_OVERLAP}+ days. With {pairs} pairs tested, about "
            f"{chance:.1f} would pass by chance (median overlap {n_med:.0f} days).{skip}"
        ),
    )


def cell(mats: dict, ia, ib, lag: int) -> tuple:
    """(corr, n) of corr(r_ia[t], r_ib[t + lag]) for any sign of lag (scalars or arrays)."""
    c, n = mats[abs(lag)]
    return (c[ia, ib], n[ia, ib]) if lag >= 0 else (c[ib, ia], n[ib, ia])
