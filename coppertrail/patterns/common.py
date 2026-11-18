"""Small helpers shared by several pattern jobs (no GUI imports)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from coppertrail.patterns.base import Context
from coppertrail.patterns.baseline import TZ


def names(ctx: Context) -> pd.DataFrame:
    """item_id -> name (and level) for the selection; unknown items get no row."""
    it = ctx.items
    return it[["item_id", "name", "level"]].drop_duplicates("item_id")


def sales_per_day(ctx: Context) -> pd.Series:
    """Latest sales/day per item from `ctx.latest` (index item_id)."""
    snap = ctx.latest
    if snap.empty:
        return pd.Series(dtype="float64", name="sales_per_day")
    return snap.set_index("item_id")["sales_per_day"].astype("float64")


def finish_ranked(df: pd.DataFrame, ctx: Context, cols: list[str]) -> pd.DataFrame:
    """Add name and sales/day, put `item_id, name` first, keep `cols` order after them."""
    out = df.merge(names(ctx)[["item_id", "name"]], on="item_id", how="left")
    out["sales_per_day"] = out["item_id"].map(sales_per_day(ctx))
    out["name"] = out["name"].fillna(out["item_id"].astype(str))
    return out[["item_id", "name", *cols]].reset_index(drop=True)


def local_hour(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert(TZ).dt.hour


def local_day(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert(TZ).dt.date


def daily_prices(h: pd.DataFrame, col: str = "min", min_hours: int = 12) -> pd.DataFrame:
    """Per item and CET day: median of hourly `col` as `price`, days with >= `min_hours` rows.

    Also `quantity` (mean listed quantity that day) when the hourly frame has it.
    """
    cols = ["item_id", "day", "price"] + (["quantity"] if "quantity" in h else [])
    if h.empty:
        return pd.DataFrame(columns=cols)
    h = h.assign(day=local_day(h["hour"]))
    g = h.groupby(["item_id", "day"])
    d = g[col].agg(["median", "size"]).rename(columns={"median": "price"})
    if "quantity" in h:
        d["quantity"] = g["quantity"].mean()
    d = d[d["size"] >= min_hours]
    d["price"] = d["price"].astype("float64")
    return d.reset_index()[cols]


def runs(flag: pd.Series) -> pd.Series:
    """Run id per row: consecutive True rows share an id; False rows get -1."""
    f = flag.fillna(False).astype(bool).to_numpy()
    start = f & ~np.concatenate([[False], f[:-1]])
    ids = np.cumsum(start) - 1
    return pd.Series(np.where(f, ids, -1), index=flag.index)


def by_hour(events: pd.DataFrame) -> pd.DataFrame:
    """Event count per CET hour of day, all 24 hours."""
    counts = local_hour(events["at"]).value_counts() if len(events) else pd.Series(dtype=int)
    hours = pd.DataFrame({"hour": range(24)})
    hours["events"] = hours["hour"].map(counts).fillna(0).astype("int64")
    return hours


def minutes(td: pd.Series | pd.Timedelta) -> pd.Series | float:
    return td / pd.Timedelta(minutes=1)


def pct(x: float) -> str:
    """Signed percent with a real minus sign: -0.123 -> '−12 %'."""
    if x is None or not np.isfinite(x):
        return "?"
    s = f"{abs(x):.0%}".replace("%", " %")
    return ("−" if x < 0 else "+") + s


def duration(mins: float) -> str:
    if mins is None or not np.isfinite(mins):
        return "?"
    m = int(round(mins))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"
