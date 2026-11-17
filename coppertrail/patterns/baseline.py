"""Reproduce the HANDOVER section 5 baseline from the archive (HANDOVER step 4).

Section 5 was computed in the chat on the 300 highest-turnover items with at least
20 sales per day, from hourly 7-day series, 2026-11-09 to 2026-11-16. This module
recomputes the same four results so the archive and the method can be checked
against them before any pattern job relies on either:

1. daily rhythm index of quantity and min buyout by CET hour,
2. evening (21:00-01:00) to next morning (07:00-13:00) flip after a 5 % cut,
3. weekly trend of listed quantity and min buyout,
4. hours where min buyout sits far below or above its 24-hour median.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from coppertrail.query import series

TZ = "Europe/Berlin"
CUT = 0.05
EVENING = (21, 22, 23, 0)  # buy window: 21:00 to 01:00 (hours starting 21..00)
MORNING = (7, 8, 9, 10, 11, 12)  # sell window: 07:00 to 13:00
TABLE_HOURS = (0, 3, 6, 7, 9, 12, 15, 18, 21, 22, 23)

# HANDOVER section 5, for side-by-side printing.
EXPECTED = {
    "rhythm_quantity": dict(
        zip(TABLE_HOURS, (111, 92, 75, 64, 70, 86, 103, 112, 115, 118, 117), strict=True)
    ),
    "rhythm_min": dict(
        zip(TABLE_HOURS, (96, 103, 104, 108, 105, 104, 101, 98, 96, 95, 95), strict=True)
    ),
    "flip_min": -3.6,
    "flip_p25": -8.6,
    "flip_positive": "58 of 299",
    "quantity_trend": 80.0,
    "below_peak": "20:00 to 00:00",
    "above_peak": "07:00 to 14:00",
}


def trim_mean(values: pd.Series, cut: float = 0.1) -> float:
    """Mean after dropping `cut` of the values at each end (scipy's trim_mean)."""
    v = np.sort(values.dropna().to_numpy(dtype=float))
    k = int(len(v) * cut)
    v = v[k : len(v) - k] if len(v) > 2 * k else v
    return float(v.mean()) if len(v) else float("nan")


def select_items(data_dir: Path, top: int = 300, min_sales: float = 20.0) -> pd.DataFrame:
    """Highest turnover (sales/day x min buyout, latest snapshot) with min sales/day."""
    snap = series.latest_snapshot(data_dir)
    snap = snap[(snap["sales_per_day"] >= min_sales) & snap["min_buyout"].notna()].copy()
    snap["turnover"] = snap["sales_per_day"] * snap["min_buyout"]
    snap = snap.sort_values("turnover", ascending=False).head(top)
    names = series.items(data_dir)[["item_id", "name"]]
    return snap.merge(names, on="item_id", how="left")[["item_id", "name", "turnover"]]


def _local(h: pd.DataFrame) -> pd.DataFrame:
    h = h.copy()
    h["local"] = h["hour"].dt.tz_convert(TZ)
    h["hod"] = h["local"].dt.hour
    return h


def _full_hours(h: pd.DataFrame) -> pd.DataFrame:
    """One row per item and hour across the item's span, gaps as NaN (for rolling windows)."""
    out = []
    for item_id, g in h.groupby("item_id"):
        g = g.set_index("hour").sort_index()
        idx = pd.date_range(g.index.min(), g.index.max(), freq="h")
        g = g.reindex(idx)
        g.index.name = "hour"
        g["item_id"] = item_id
        out.append(g.reset_index())
    return pd.concat(out, ignore_index=True) if out else h


def rhythm(h: pd.DataFrame) -> pd.DataFrame:
    """Index by CET hour: 100 = the item's mean over +/-12 h; 10 % trimmed mean over items."""
    full = _full_hours(h[["item_id", "hour", "min", "quantity"]])
    rows = []
    for col in ("quantity", "min"):
        roll = full.groupby("item_id")[col].transform(
            lambda s: s.rolling(25, center=True, min_periods=18).mean()
        )
        full[f"{col}_idx"] = 100 * full[col] / roll
    full = _local(full)
    per_item = full.groupby(["item_id", "hod"])[["quantity_idx", "min_idx"]].mean().reset_index()
    for hod, g in per_item.groupby("hod"):
        rows.append(
            {
                "hour": hod,
                "quantity": trim_mean(g["quantity_idx"]),
                "min": trim_mean(g["min_idx"]),
                "items": int(g["min_idx"].notna().sum()),
            }
        )
    return pd.DataFrame(rows)


def flip(h: pd.DataFrame) -> pd.DataFrame:
    """Per item and night: buy in the evening window, sell next morning after the cut.

    The night belongs to the evening's local date; 00:00 counts with the previous evening.
    """
    h = _local(h)
    night = h["local"].dt.normalize()
    h["night"] = night.where(h["hod"] != 0, night - pd.Timedelta(days=1))
    eve = h[h["hod"].isin(EVENING)].groupby(["item_id", "night"])[["min", "p25"]].mean()
    h["morning_of"] = night - pd.Timedelta(days=1)
    morn = h[h["hod"].isin(MORNING)].groupby(["item_id", "morning_of"])["min"].mean()
    morn.index = morn.index.set_names(["item_id", "night"])
    df = eve.join(morn.rename("sell"), how="inner").dropna()
    df["ret_min"] = df["sell"] * (1 - CUT) / df["min"] - 1
    df["ret_p25"] = df["sell"] * (1 - CUT) / df["p25"] - 1
    return df.reset_index()


def flip_summary(nights: pd.DataFrame, names: pd.DataFrame) -> dict:
    # Median over an item's nights: a few nights with huge swings would dominate a mean.
    per_item = nights.groupby("item_id").agg(
        ret_min=("ret_min", "median"),
        ret_p25=("ret_p25", "median"),
        nights=("ret_min", "size"),
        won=("ret_min", lambda s: int((s > 0).sum())),
    )
    per_item = per_item.join(names.set_index("item_id")["name"])
    robust = per_item[(per_item["won"] >= 6) & (per_item["nights"] >= 7)]
    return {
        "items": len(per_item),
        "median_min": 100 * float(per_item["ret_min"].median()),
        "median_p25": 100 * float(per_item["ret_p25"].median()),
        "positive": int((per_item["ret_min"] > 0).sum()),
        "robust": robust.sort_values("ret_min", ascending=False)["name"].tolist(),
    }


def trend(h: pd.DataFrame, names: pd.DataFrame, min_hours: int = 20) -> dict:
    """Mean of the first full CET day against the last one, per item.

    Whole local days keep the daily rhythm out of the comparison; a day counts as full
    with at least `min_hours` hourly rows (the API has gaps at night).
    """
    h = _local(h)
    h["day"] = h["local"].dt.date
    daily = h.groupby(["item_id", "day"]).agg(
        n=("min", "size"), quantity=("quantity", "mean"), min=("min", "mean")
    )
    daily = daily[daily["n"] >= min_hours].reset_index()
    rows = []
    for item_id, g in daily.groupby("item_id"):
        if len(g) < 2:
            continue
        first, last = g.iloc[0], g.iloc[-1]
        rows.append(
            {
                "item_id": item_id,
                "first_day": first["day"],
                "last_day": last["day"],
                "quantity": last["quantity"] / first["quantity"] - 1,
                "min": last["min"] / first["min"] - 1,
            }
        )
    df = pd.DataFrame(rows, columns=["item_id", "first_day", "last_day", "quantity", "min"])
    df = df.merge(names, on="item_id", how="left")
    return {
        "items": len(df),
        "median_quantity": 100 * float(df["quantity"].median()),
        "median_min": 100 * float(df["min"].median()),
        "fallers": df.nsmallest(8, "min")[["name", "min"]].to_records(index=False).tolist(),
        "risers": df.nlargest(8, "min")[["name", "min"]].to_records(index=False).tolist(),
    }


def outliers(h: pd.DataFrame, below: float = 0.30, above: float = 0.40) -> pd.DataFrame:
    """Share of hours by CET hour where min buyout is far from its 24-hour median."""
    full = _full_hours(h[["item_id", "hour", "min"]])
    ref = full.groupby("item_id")["min"].transform(lambda s: s.rolling(24, min_periods=12).median())
    full["low"] = full["min"] < ref * (1 - below)
    full["high"] = full["min"] > ref * (1 + above)
    full = _local(full[full["min"].notna() & ref.notna()])
    out = full.groupby("hod")[["low", "high"]].sum().reset_index()
    return out.rename(columns={"hod": "hour"})


def _peak(hours: pd.DataFrame, col: str, width: int) -> str:
    """The `width`-hour window (wrapping midnight) holding most events."""
    counts = hours.set_index("hour")[col].reindex(range(24), fill_value=0).to_numpy()
    best = max(range(24), key=lambda s: sum(counts[(s + i) % 24] for i in range(width)))
    return f"{best:02d}:00 to {(best + width) % 24:02d}:00"


@dataclass
class Baseline:
    start: date
    end: date
    items: int
    hours: int
    rhythm: pd.DataFrame
    flip: dict
    trend: dict
    outliers: pd.DataFrame
    peaks: dict = field(default_factory=dict)


def baseline(data_dir: Path, start: date, end: date) -> Baseline:
    sel = select_items(data_dir)
    h = series.hourly(data_dir, sel["item_id"].tolist(), start, end)
    names = sel[["item_id", "name"]]
    out = outliers(h)
    return Baseline(
        start=start,
        end=end,
        items=int(h["item_id"].nunique()),
        hours=len(h),
        rhythm=rhythm(h),
        flip=flip_summary(flip(h), names),
        trend=trend(h, names),
        outliers=out,
        peaks={"below": _peak(out, "low", 4), "above": _peak(out, "high", 7)},
    )


def format_baseline(b: Baseline) -> str:
    e = EXPECTED
    lines = [
        f"Baseline {b.start} to {b.end}: {b.items} items, {b.hours} hourly rows",
        "",
        "Daily rhythm index (ours / HANDOVER)",
        "hour CET   " + " ".join(f"{h:>7}" for h in TABLE_HOURS),
    ]
    r = b.rhythm.set_index("hour")
    for col, key in (("quantity", "rhythm_quantity"), ("min", "rhythm_min")):
        cells = [f"{r[col].get(h, float('nan')):>3.0f}/{e[key][h]:<3}" for h in TABLE_HOURS]
        lines.append(f"{col:<10} " + " ".join(cells))
    f = b.flip
    lines += [
        "",
        f"Flip evening->morning, {CUT:.0%} cut, {f['items']} items",
        f"  median at min buyout {f['median_min']:+.1f} % (HANDOVER {e['flip_min']:+.1f} %)",
        f"  median at p25        {f['median_p25']:+.1f} % (HANDOVER {e['flip_p25']:+.1f} %)",
        f"  positive items       {f['positive']} of {f['items']} (HANDOVER {e['flip_positive']})",
        f"  robust (>= 6 of 7)   {', '.join(f['robust'][:10]) or '-'}",
    ]
    t = b.trend
    lines += [
        "",
        f"Trend first -> last full CET day, {t['items']} items",
        f"  listed quantity median {t['median_quantity']:+.0f} % "
        f"(HANDOVER +{e['quantity_trend']:.0f} %)",
        f"  min buyout median      {t['median_min']:+.0f} %",
        "  fallers " + ", ".join(f"{n} {v:+.0%}" for n, v in t["fallers"]),
        "  risers  " + ", ".join(f"{n} {v:+.0%}" for n, v in t["risers"]),
        "",
        "Outliers vs 24 h median (hours, CET)",
        f"  >30 % below peaks {b.peaks['below']} (HANDOVER {e['below_peak']})",
        f"  >40 % above peaks {b.peaks['above']} (HANDOVER {e['above_peak']})",
    ]
    return "\n".join(lines)
