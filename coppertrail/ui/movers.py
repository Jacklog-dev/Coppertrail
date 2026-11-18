"""Payloads for Movers & outliers (HANDOVER 8b "Views", mock-up Movers).

Pure functions from hourly rows (one per snapshot) and the `mispricings` job to JSON-able dicts; the
bridge reads and caches. Spec: `docs/superpowers/specs/2026-11-17-patterns-movers-views.md`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import pandas as pd

from coppertrail.patterns import PatternResult
from coppertrail.query.catalog import Item
from coppertrail.ui import format as fmt
from coppertrail.ui.viewdata import FULL_DAY_HOURS, TZ, coin, daily_table, finite, nums, plural

RANGES = {"24h": "24 h", "7d": "7 d", "30d": "30 d"}
DEFAULT_RANGE = "7d"
RANGE_DAYS = {"7d": 7, "30d": 30}
MIN_SALES = 10  # movers: items with fewer sales/day are left out (rare items swing wildly)
ROWS = 6
BLOCK_HOURS = 3  # 24 h: the last 3 hours against the same 3 hours a day earlier
THRESHOLDS = (0.5, 0.6, 0.7)  # the job flags 30 % dips and deeper, so 70 % is the widest
DEFAULT_THRESHOLD = 0.7
MISPRICING_ROWS = 50
WINDOW = timedelta(hours=24)


def read_days(rng: str) -> int:
    """Days of hourly data `movers` needs before the archive's last day."""
    return 2 if rng == "24h" else RANGE_DAYS[rng] + 1


def _compare_hours(h: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, list], str]:
    t = h["hour"].max()
    block = pd.Timedelta(hours=BLOCK_HOURS)

    def agg(part: pd.DataFrame) -> pd.DataFrame:
        return part.groupby("item_id").agg(price=("min", "median"), qty=("quantity", "mean"))

    now = agg(h[h["hour"] > t - block])
    base = agg(h[(h["hour"] > t - WINDOW - block) & (h["hour"] <= t - WINDOW)])
    day = h[h["hour"] > t - WINDOW].sort_values("hour")
    sparks = {int(k): list(g["min"]) for k, g in day.groupby("item_id")}
    sub = f"{fmt.short_datetime(t - WINDOW)} – {fmt.short_datetime(t)}"
    return now.join(base.add_suffix("_base"), how="inner"), sparks, sub


def _compare_days(h: pd.DataFrame, days: int) -> tuple[pd.DataFrame, dict[int, list], str]:
    d = daily_table(h)
    full = d[d["hours"] >= FULL_DAY_HOURS]
    if full.empty:
        return pd.DataFrame(), {}, ""
    all_days: list[date] = sorted(set(full["day"]))
    last = all_days[-1]
    earlier = [x for x in all_days if last - timedelta(days=days) <= x < last]
    if not earlier:
        return pd.DataFrame(), {}, ""
    base_day = earlier[0]

    def at(day: date) -> pd.DataFrame:
        return full[full["day"] == day].set_index("item_id")[["price", "qty"]]

    span = full[full["day"] >= base_day].sort_values("day")
    sparks = {int(k): list(g["price"]) for k, g in span.groupby("item_id")}
    sub = fmt.date_range(base_day, last)
    if base_day > last - timedelta(days=days):
        sub += f" · archive starts {fmt.day_month(all_days[0])}"
    return at(last).join(at(base_day).add_suffix("_base"), how="inner"), sparks, sub


def movers(hourly: pd.DataFrame, items: Sequence[Item], rng: str) -> dict:
    rng = rng if rng in RANGES else DEFAULT_RANGE
    out: dict = {
        "range": rng,
        "ranges": [{"key": k, "label": v} for k, v in RANGES.items()],
    }
    if hourly.empty:
        cmp, sparks, sub = pd.DataFrame(), {}, ""
    elif rng == "24h":
        cmp, sparks, sub = _compare_hours(hourly)
    else:
        cmp, sparks, sub = _compare_days(hourly, RANGE_DAYS[rng])
    by_id = {i.item_id: i for i in items}
    card_sub = " · ".join(p for p in (sub, f"items with {MIN_SALES}+ sales/day") if p)
    rows: list[dict] = []
    for item_id, r in cmp.iterrows() if len(cmp) else []:
        item = by_id.get(int(item_id))
        if item is None or item.sales_per_day < MIN_SALES:
            continue
        if not (finite(r["price"]) and finite(r["price_base"]) and r["price_base"] > 0):
            continue
        change = float(r["price"] / r["price_base"] - 1)
        supply = (
            float(r["qty"] / r["qty_base"] - 1)
            if finite(r["qty"]) and finite(r["qty_base"]) and r["qty_base"] > 0
            else None
        )
        rows.append(
            {
                "id": item.item_id,
                "name": item.name,
                "spark": nums(sparks.get(int(item_id), []), 1),
                "dir": fmt.direction(change),
                "price": coin(item.min_buyout),
                "change": fmt.change(change),
                "supply": f"{fmt.signed_percent(supply)} supply" if supply is not None else "–",
                "sales": fmt.count(item.sales_per_day),
                "_c": change,
            }
        )
    risers = sorted((r for r in rows if r["_c"] > 0), key=lambda r: -r["_c"])[:ROWS]
    fallers = sorted((r for r in rows if r["_c"] < 0), key=lambda r: r["_c"])[:ROWS]
    for r in rows:
        del r["_c"]
    for key, picked, word in (("risers", risers, "rose"), ("fallers", fallers, "fell")):
        card: dict = {"sub": card_sub, "rows": picked}
        if not picked:
            card["note"] = (
                f"No item {word} in this range." if sub else "Too little history for this range."
            )
        out[key] = card
    return out


def threshold_of(value) -> float:
    try:
        v = round(float(value), 2)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return v if v in THRESHOLDS else DEFAULT_THRESHOLD


def mispricings_now(
    result: PatternResult | None,
    hourly: pd.DataFrame,
    items: Sequence[Item],
    group_of: dict[int, str],
    threshold: float,
) -> dict:
    """Mispricings found in the last 24 h of snapshots, below `threshold` x the usual price.

    Usual = the job's reference (median p25 of the prior 6 h): in a falling market the
    30-day median lags far above every recent listing.
    """
    out: dict = {
        "threshold": threshold,
        "thresholds": [{"value": v, "label": f"below {round(v * 100)} %"} for v in THRESHOLDS],
        "usualLabel": "Usual (6 h median)",
        "rows": [],
    }
    if hourly.empty:
        return {**out, "sub": "No data yet", "note": "The archive has no hourly data yet."}
    t = hourly["observed_at"].max()
    ev = None if result is None or not result.ready else result.charts.get("events")
    header = f"{fmt.local_datetime(t.to_pydatetime())} · last 24 h"
    if ev is None or ev.empty:
        return {**out, "sub": f"{header} · 0 items", "note": "No mispricings in the last 24 hours."}
    recent = ev[ev["at"] >= t - WINDOW].sort_values("at").groupby("item_id").tail(1)
    window = hourly[hourly["observed_at"] >= t - WINDOW]
    typical = window.groupby("item_id").agg(low=("p25", "median"), high=("p75", "median"))
    qty = hourly.set_index(["item_id", "observed_at"])["quantity"]
    by_id = {i.item_id: i for i in items}
    last_day = t.tz_convert(TZ).date()
    rows = []
    for e in recent.itertuples():
        item = by_id.get(int(e.item_id))
        u = e.reference
        if item is None or not finite(u) or u <= 0 or not finite(e.min):
            continue
        if e.min >= threshold * u:
            continue
        typ = typical.loc[e.item_id] if e.item_id in typical.index else None
        at = pd.Timestamp(e.at)
        q = qty.get((e.item_id, at))
        rows.append(
            (
                float(e.min / u - 1),
                {
                    "id": item.item_id,
                    "name": item.name,
                    "group": group_of.get(item.item_id, item.item_class),
                    "price": coin(e.min),
                    "usual": coin(u),
                    "discount": fmt.change(float(e.min / u - 1)),
                    "range": {
                        "low": float(typ["low"]) if typ is not None else float(e.min),
                        "high": float(typ["high"]) if typ is not None else float(u),
                        "usual": float(u),
                        "current": float(e.min),
                    },
                    "qty": fmt.count(float(q)) if finite(q) else "–",
                    "seen": (
                        f"{at.tz_convert(TZ):%H:%M}"
                        if at.tz_convert(TZ).date() == last_day
                        else fmt.short_datetime(at.to_pydatetime())
                    ),
                },
            )
        )
    rows.sort(key=lambda r: r[0])
    out["rows"] = [r for _, r in rows[:MISPRICING_ROWS]]
    out["sub"] = f"{header} · {plural(len(rows), 'item')}"
    if not rows:
        out["note"] = f"Nothing below {round(threshold * 100)} % of its usual price right now."
    return out
