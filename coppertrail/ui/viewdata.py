"""Payloads for the Market overview and Item detail views (HANDOVER 8b "Views").

Pure functions from pandas frames and pattern results to JSON-able dicts: no locks, no
caching (the bridge does both). Every display string comes from `format.py`; charts get
unix seconds on x and plain numbers (copper for prices) on y. Spec:
`docs/superpowers/specs/2026-11-17-market-item-views.md`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pandas as pd

from coppertrail.patterns.base import PatternResult, events_frame
from coppertrail.query.catalog import Item
from coppertrail.ui import format as fmt

TZ = fmt.LOCAL_TZ
FULL_DAY_HOURS = 12  # a CET day counts for "7 d" comparisons with this many hourly rows
WEEK = 7
COVERAGE = 0.8  # supply chart: hours where fewer items reported are left out
MAX_EVENTS = 4  # rows in "What changed"
MAX_ITEM_EVENTS = 50
BUCKET_HOURS_LONG = 6  # price and supply chart beyond a week
RHYTHM_DAYS = 7

TYPE_LABEL = {"mispricing": "Mispricing", "supply_shock": "Supply shock", "buyout": "Buyout"}
MARKER_KIND = {"mispricing": "mispricing", "supply_shock": "shock", "buyout": "buyout"}
SORTS = {
    "sales": "sales/day",
    "name": "name",
    "price": "lowest buyout",
    "change": "weekly change",
}
DAILY_COLS = ["item_id", "day", "price", "p25", "qty", "hours"]


# Small helpers ------------------------------------------------------------------------


def finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def num(x, digits: int = 4) -> float | None:
    return round(float(x), digits) if finite(x) else None


def nums(values: Iterable, digits: int = 4) -> list[float | None]:
    return [num(v, digits) for v in values]


def unix(ts) -> int:
    return int(pd.Timestamp(ts).timestamp())


def local_midnight(d: date) -> int:
    """A CET day as the unix second of its local midnight (daily chart points)."""
    return int(datetime.combine(d, time(), TZ).timestamp())


def utc_bounds(lo: date, hi: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The inclusive UTC day range as [start, end) instants (as `query.series` reads it)."""
    start = pd.Timestamp(datetime.combine(lo, time(), UTC))
    return start, pd.Timestamp(datetime.combine(hi + timedelta(days=1), time(), UTC))


def coin(copper) -> dict | None:
    if not finite(copper) or float(copper) < 0:
        return None
    c = int(round(float(copper)))
    return {"parts": [[n, u] for n, u in fmt.coin_parts(c)], "text": fmt.coins_text(c)}


def range_sub(lo: date, hi: date, *extra: str) -> str:
    """`17 Oct – 16 Nov 2026 · 30 d · extra`: every chart states its date range."""
    days = (hi - lo).days + 1
    return " · ".join([fmt.date_range(lo, hi), f"{days} d", *[e for e in extra if e]])


def plural(n: int, word: str) -> str:
    return f"{fmt.thousands(n)} {word}{'' if n == 1 else 's'}"


# Daily table and "7 d" comparisons ------------------------------------------------------


def daily_table(hourly: pd.DataFrame) -> pd.DataFrame:
    """Per item and CET day: median min (`price`), median p25, mean quantity, hourly rows."""
    if hourly.empty:
        return pd.DataFrame(columns=DAILY_COLS)
    h = hourly.assign(day=hourly["hour"].dt.tz_convert(TZ).dt.date)
    out = (
        h.groupby(["item_id", "day"])
        .agg(
            price=("min", "median"),
            p25=("p25", "median"),
            qty=("quantity", "mean"),
            hours=("min", "size"),
        )
        .reset_index()
    )
    return out[DAILY_COLS]


def week_days(daily: pd.DataFrame) -> tuple[date, date] | None:
    """(base, last): the last full CET day and the full day a week before it.

    Without that day (archive gap or a short archive) the first full day after it.
    """
    full = daily[daily["hours"] >= FULL_DAY_HOURS]
    if full.empty:
        return None
    days = sorted(set(full["day"]))
    last = days[-1]
    later = [d for d in days if last - timedelta(days=WEEK) <= d < last]
    return (later[0], last) if later else None


def _pair(daily: pd.DataFrame, col: str, days: tuple[date, date]) -> pd.DataFrame:
    full = daily[(daily["hours"] >= FULL_DAY_HOURS) & daily["day"].isin(days)]
    wide = full.pivot_table(index="item_id", columns="day", values=col, aggfunc="first")
    if days[0] not in wide.columns or days[1] not in wide.columns:
        return pd.DataFrame(columns=["base", "last"])
    return wide[[days[0], days[1]]].set_axis(["base", "last"], axis=1).dropna()


def week_change(daily: pd.DataFrame) -> pd.Series:
    """item_id -> price change over the week (signed fraction)."""
    days = week_days(daily)
    if days is None:
        return pd.Series(dtype="float64")
    p = _pair(daily, "price", days)
    p = p[p["base"] > 0]
    return (p["last"] / p["base"] - 1).rename("change")


def week_base_price(daily: pd.DataFrame, item_id: int) -> float | None:
    days = week_days(daily)
    if days is None:
        return None
    row = daily[(daily["item_id"] == item_id) & (daily["day"] == days[0])]
    return float(row["price"].iloc[0]) if len(row) and finite(row["price"].iloc[0]) else None


def week_supply(daily: pd.DataFrame) -> tuple[float | None, float | None]:
    """(change of the summed daily mean quantity, last day's sum), items on both days."""
    days = week_days(daily)
    if days is None:
        return None, None
    q = _pair(daily, "qty", days)
    if q.empty or q["base"].sum() <= 0:
        return None, None
    return float(q["last"].sum() / q["base"].sum() - 1), float(q["last"].sum())


# Market overview ---------------------------------------------------------------------------


def _median_change(changes: pd.Series) -> float | None:
    return float(changes.median()) if len(changes) else None


def overview_tiles(
    *,
    total: int,
    shown: int,
    daily: pd.DataFrame,
    classes: pd.Series,
    inflation: PatternResult | None,
    economy: pd.DataFrame,
) -> list[dict]:
    """The headline tiles; the last two only show from 2400 px (`extra`)."""
    changes = week_change(daily)
    med = _median_change(changes)
    foot = []
    for group in ("farmable", "scarce"):
        part = changes[changes.index.isin(classes[classes == group].index)]
        if len(part):
            foot.append(f"{group} {fmt.signed_percent(float(part.median()))}")
    supply, units = week_supply(daily)
    div = _latest_divergence(inflation)
    gold_now, gold_change = _economy_week(economy, "value")
    auctions_now, auctions_change = _economy_week(economy, "auctions")
    return [
        {
            "label": "Items tracked",
            "value": fmt.thousands(total),
            "foot": f"{fmt.thousands(shown)} pass filters",
        },
        {
            "label": "Median price · 7 d",
            "change": fmt.change(med),
            "foot": ", ".join(foot) if foot else plural(len(changes), "item") + " compared",
        },
        {
            "label": "Supply · 7 d",
            "change": fmt.change(supply),
            "foot": f"{fmt.count(units)} units listed" if units is not None else "no full week yet",
        },
        {
            "label": "Index divergence",
            "value": fmt.points(div) if div is not None else "–",
            "accent": div is not None,
            "foot": "scarce minus farmable",
        },
        {
            "label": "Gold listed · 7 d",
            "coin": coin(gold_now),
            "foot": _change_foot(gold_change, "whole market"),
            "extra": True,
        },
        {
            "label": "Auctions · 7 d",
            "value": fmt.thousands(int(auctions_now)) if auctions_now is not None else "–",
            "foot": _change_foot(auctions_change, "whole market"),
            "extra": True,
        },
    ]


def _change_foot(change: float | None, tail: str) -> list:
    c = fmt.change(change)
    return [{"change": c}, f" · {tail}"] if c else [tail]


def _latest_divergence(result: PatternResult | None) -> float | None:
    if result is None or not result.ready:
        return None
    div = result.charts.get("divergence")
    if div is None or div.empty:
        return None
    v = div["divergence"].iloc[-1]
    return float(v) if finite(v) else None


def _economy_week(economy: pd.DataFrame, col: str) -> tuple[float | None, float | None]:
    """Latest value of an economy column and its change against 7 days earlier."""
    e = economy.dropna(subset=[col]).sort_values("day")
    if e.empty:
        return None, None
    last_day, last = e["day"].iloc[-1], float(e[col].iloc[-1])
    week = e[e["day"] >= last_day - timedelta(days=WEEK)]
    base = float(week[col].iloc[0]) if len(week) > 1 else None
    return last, (last / base - 1) if base else None


def index_chart(result: PatternResult | None, lo: date, hi: date) -> dict:
    """Price index farmable vs scarce goods (pattern `inflation`), baseline 100."""
    out: dict = {"sub": range_sub(lo, hi)}
    if result is None or not result.ready:
        out["note"] = "Too little history for an index."
        return out
    idx = result.charts.get("index")
    if idx is None or idx.empty:
        out["note"] = "No farmable or scarce goods in this filter."
        return out
    wide = idx.pivot(index="day", columns="group", values="index").sort_index()
    days = list(wide.index)
    out["sub"] = range_sub(lo, hi, f"100 = {fmt.day_month(days[0])}")
    out["x"] = [local_midnight(d) for d in days]
    for group in ("scarce", "farmable"):
        out[group] = nums(wide[group]) if group in wide.columns else None
    if out["scarce"] is not None and out["farmable"] is not None:
        out["divergence"] = nums(wide["scarce"] - wide["farmable"])
    else:
        missing = "scarce" if out["scarce"] is None else "farmable"
        out["note"] = f"No {missing} goods in this filter, so no divergence."
    return out


def rhythm_chart(result: PatternResult | None, lo: date, hi: date, gap: dict | None) -> dict:
    """Daily rhythm over 24 h (pattern `daily_rhythm`, market_day): supply and lowest buyout."""
    out: dict = {"sub": range_sub(lo, hi, "100 = daily mean")}
    if gap is not None:
        out["gap"] = gap
        return out
    md = None if result is None else result.charts.get("market_day")
    if md is None or md.empty:
        out["note"] = "No hourly data in this filter."
        return out
    md = md.set_index("hour").reindex(range(24))
    out["hours"] = list(range(24))
    out["price"] = nums(md["min_idx"], 2)
    out["supply"] = nums(md["quantity_idx"], 2)
    labels = []
    for key, values in (("price", md["min_idx"]), ("supply", md["quantity_idx"])):
        v = values.dropna()
        if v.empty:
            continue
        for hour in (int(v.idxmin()), int(v.idxmax())):
            labels.append(
                {
                    "series": key,
                    "x": hour,
                    "y": round(float(v[hour]), 2),
                    "text": f"{round(float(v[hour]))} · {fmt.hour_of_day(hour)}",
                    "below": hour == int(v.idxmin()),
                }
            )
    out["labels"] = labels
    return out


def rhythm_by_group(
    result: PatternResult | None, groups: Sequence[tuple[str, set[int]]], lo: date, hi: date
) -> dict:
    """Per item group: median over its items of the lowest buyout at 07:00 against 23:00."""
    out: dict = {"sub": range_sub(lo, hi, "lowest buyout, 07:00 vs 23:00"), "rows": []}
    td = None if result is None or not result.ready else result.charts.get("typical_day")
    if td is None or td.empty:
        out["note"] = "Needs the daily rhythm."
        return out
    wide = td.pivot_table(index="item_id", columns="hour", values="min_idx")
    if 7 not in wide.columns or 23 not in wide.columns:
        out["note"] = "No 07:00 or 23:00 prices yet."
        return out
    ratio = (wide[7] / wide[23] - 1).dropna()
    rows = []
    for name, ids in groups:
        part = ratio[ratio.index.isin(ids)]
        if len(part):
            rows.append((name, float(part.median()), len(part)))
    top = max((abs(v) for _, v, _ in rows), default=0) or 1
    out["rows"] = [
        {
            "name": name,
            "change": fmt.change(v),
            "share": round(abs(v) / top, 3),
            "items": plural(n, "item"),
        }
        for name, v, n in sorted(rows, key=lambda r: -r[1])
    ]
    if not rows:
        out["note"] = "No group has items in this filter."
    return out


def supply_chart(
    hourly: pd.DataFrame, lo: date, hi: date, week: tuple[float | None, float | None]
) -> dict:
    """Total listed quantity per hour over the filtered items."""
    out: dict = {"sub": range_sub(lo, hi)}
    if hourly.empty:
        out["note"] = "No hourly data in this filter."
        return out
    g = hourly.groupby("hour").agg(total=("quantity", "sum"), items=("item_id", "nunique"))
    typical = g["items"].median()
    g.loc[g["items"] < COVERAGE * typical, "total"] = np.nan
    out["x"] = [unix(t) for t in g.index]
    out["values"] = nums(g["total"], 0)
    kept = g["total"].dropna()
    out["value"] = fmt.count(float(kept.iloc[-1])) if len(kept) else "–"
    out["change"] = fmt.change(week[0])
    return out


def gold_chart(economy: pd.DataFrame, lo: date, hi: date) -> dict:
    """Total gold listed per day (economy totals: the whole market, not the filter)."""
    out: dict = {"sub": range_sub(lo, hi, "whole market")}
    e = economy[(economy["day"] >= lo) & (economy["day"] <= hi)].dropna(subset=["value"])
    if e.empty:
        out["note"] = "No market totals in this range."
        return out
    e = e.sort_values("day")
    out["x"] = [local_midnight(d) for d in e["day"]]
    out["values"] = nums(e["value"], 0)
    last, change = _economy_week(economy[economy["day"] <= hi], "value")
    out["value"] = coin(last)
    out["change"] = fmt.change(change)
    return out


def empty_events() -> pd.DataFrame:
    return events_frame()


def _event_frame(results: Sequence[PatternResult | None]) -> pd.DataFrame:
    frames = [r.events for r in results if r is not None and r.events is not None]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else empty_events()


def event_row(ev, names: dict[int, str]) -> dict:
    at = pd.Timestamp(ev.at).to_pydatetime()
    return {
        "id": int(ev.item_id),
        "name": names.get(int(ev.item_id), str(ev.item_id)),
        "kind": MARKER_KIND[ev.type],
        "type": TYPE_LABEL[ev.type],
        "when": fmt.short_datetime(at),
        "t": unix(ev.at),
        "detail": str(ev.detail),
    }


def what_changed(
    results: Sequence[PatternResult | None],
    names: dict[int, str],
    sales: dict[int, float],
    lo: date,
    hi: date,
) -> dict:
    """The strongest events of the last week, one type after the other (round robin).

    Strength = the event's size (capped at 100 %) x log10(10 + sales/day), so a rare book
    page jumping 2,000 % does not crowd out a staple herb dropping 60 %.
    """
    ev = _event_frame(results)
    out: dict = {"sub": fmt.date_range(lo, hi), "rows": []}
    if ev.empty:
        out["note"] = "Nothing unusual in the last 7 days."
        return out
    turnover = np.log10(10 + ev["item_id"].map(sales).fillna(0).clip(lower=0))
    ev = ev.assign(strength=ev["magnitude"].abs().clip(upper=1) * turnover).sort_values(
        ["strength", "at"], ascending=[False, False]
    )
    queues = [list(g.itertuples()) for _, g in ev.groupby("type", sort=False)]
    picked = []
    while len(picked) < MAX_EVENTS and any(queues):
        for q in queues:
            if q and len(picked) < MAX_EVENTS:
                picked.append(q.pop(0))
    out["rows"] = [event_row(e, names) for e in picked]
    out["sub"] = f"{fmt.date_range(lo, hi)} · {plural(len(ev), 'event')}"
    return out


# Item list and item detail --------------------------------------------------------------


def class_line(item: Item, subclass: str | None) -> str:
    return " · ".join(p for p in (subclass, item.item_class) if p)


def item_list(
    items: Sequence[Item],
    changes: pd.Series,
    details: dict[int, dict],
    sort: str,
    limit: int,
) -> dict:
    sort = sort if sort in SORTS else "sales"
    ch = changes.to_dict()
    keys = {
        "sales": lambda i: (-i.sales_per_day, i.name.casefold()),
        "name": lambda i: i.name.casefold(),
        "price": lambda i: (-(i.min_buyout or -1), i.name.casefold()),
        "change": lambda i: (-ch.get(i.item_id, -math.inf), i.name.casefold()),
    }
    rows = sorted(items, key=keys[sort])
    more = len(rows) - limit
    return {
        "sort": sort,
        "sorts": [{"key": k, "label": v} for k, v in SORTS.items()],
        "sub": f"{plural(len(rows), 'item')} · sorted by {SORTS[sort]}",
        "more": f"first {fmt.thousands(limit)} shown" if more > 0 else "",
        "rows": [
            {
                "id": i.item_id,
                "name": i.name,
                "class": class_line(i, details.get(i.item_id, {}).get("subclass")),
                "price": coin(i.min_buyout),
                "change": fmt.change(ch.get(i.item_id)),
            }
            for i in rows[:limit]
        ],
    }


def buckets(h: pd.DataFrame, hours: int) -> pd.DataFrame:
    """Hourly rows averaged into `hours`-hour buckets (1 = unchanged)."""
    if hours <= 1 or h.empty:
        return h[["hour", "min", "p25", "quantity"]].reset_index(drop=True)
    b = h.assign(hour=h["hour"].dt.floor(f"{hours}h"))
    return b.groupby("hour", as_index=False)[["min", "p25", "quantity"]].mean()


def hour_profile(h: pd.DataFrame, lo: date, hi: date) -> dict:
    """Hour-of-day profile of the lowest buyout, 100 = the CET day's mean."""
    out: dict = {"sub": range_sub(lo, hi, "100 = daily mean")}
    h = h.dropna(subset=["min"])
    h = h[h["min"] > 0]
    if h.empty:
        out["note"] = "No hourly prices in this range."
        return out
    local = h["hour"].dt.tz_convert(TZ)
    h = h.assign(day=local.dt.date, hod=local.dt.hour)
    h = h.assign(idx=100 * h["min"] / h.groupby("day")["min"].transform("mean"))
    prof = h.groupby("hod")["idx"].mean().reindex(range(24))
    out["hours"] = list(range(24))
    out["values"] = nums(prof, 2)
    p = prof.dropna()
    lo_h, hi_h = int(p.idxmin()), int(p.idxmax())
    out["cheapest"] = {"hour": lo_h, "text": f"{fmt.FALL} cheapest {fmt.hour_of_day(lo_h)}"}
    out["dearest"] = {"hour": hi_h, "text": f"{fmt.RISE} dearest {fmt.hour_of_day(hi_h)}"}
    out["spread"] = f"Spread {fmt.share(float(p.max() / p.min() - 1))}" if p.min() > 0 else ""
    return out


def item_header(item: Item, subclass: str | None, groups: list[str], history_days: int) -> dict:
    parts = [class_line(item, subclass)]
    if groups:
        parts.append(f"{'group' if len(groups) == 1 else 'groups'} {', '.join(groups)}")
    parts.append(f"{plural(history_days, 'day')} of history")
    return {"id": item.item_id, "name": item.name, "sub": " · ".join(p for p in parts if p)}


def item_tiles(
    item: Item,
    snapshot: pd.Series | None,
    window: pd.DataFrame,
    base_price: float | None,
    vendor_price: int | None,
    lo: date,
    hi: date,
) -> list[dict]:
    low = item.min_buyout
    median_7d = None if snapshot is None else snapshot.get("median_7d")
    p25 = window["p25"].tail(24 * WEEK).median() if len(window) else None
    qty = window["quantity"].dropna()
    days = (hi - lo).days + 1
    qty_change = float(qty.iloc[-1] / qty.mean() - 1) if len(qty) and qty.mean() > 0 else None
    price_change = (low / base_price - 1) if low and base_price else None
    vendor_foot: list = ["not collected yet"]
    if vendor_price:
        vendor_foot = (
            [
                f"buyout is {fmt.share(abs(low / vendor_price - 1))} "
                f"{'above' if low >= vendor_price else 'below'} floor"
            ]
            if low
            else ["no buyout listed"]
        )
    return [
        {
            "label": "Lowest buyout",
            "coin": coin(low),
            "foot": [{"change": fmt.change(price_change)}, " vs 7 d ago"]
            if price_change is not None
            else ["latest price table"],
        },
        {
            "label": "7-day median",
            "coin": coin(median_7d),
            "foot": ["lower quartile ", {"coin": coin(p25)}] if finite(p25) else ["–"],
        },
        {
            "label": "Sales per day",
            "value": fmt.count(item.sales_per_day),
            "foot": ["latest price table"],
        },
        {
            "label": "Listed quantity",
            "value": fmt.count(float(qty.iloc[-1])) if len(qty) else "–",
            "foot": [{"change": fmt.change(qty_change)}, f" vs {days} d mean"]
            if qty_change is not None
            else ["–"],
        },
        {
            "label": "Vendor price (floor)",
            "coin": coin(vendor_price) if vendor_price else None,
            "value": None if vendor_price else "–",
            "foot": vendor_foot,
        },
    ]


def price_chart(
    window: pd.DataFrame,
    events: pd.DataFrame,
    vendor_price: int | None,
    lo: date,
    hi: date,
) -> dict:
    """Lowest buyout and lower quartile with the band, listed quantity below, markers."""
    days = (hi - lo).days + 1
    size = 1 if days <= WEEK else BUCKET_HOURS_LONG
    out: dict = {"sub": range_sub(lo, hi, f"{size} h buckets")}
    if window.empty:
        out["note"] = "No hourly prices in this range."
        return out
    b = buckets(window, size)
    x = [unix(t) for t in b["hour"]]
    out["x"] = x
    out["min"] = nums(b["min"], 1)
    out["p25"] = nums(b["p25"], 1)
    out["quantity"] = nums(b["quantity"], 0)
    shock_at = (
        events.loc[events["type"] == "supply_shock", "at"].dt.floor(f"{size}h")
        if len(events)
        else pd.Series(dtype="datetime64[ns, UTC]")
    )
    shock_x = {unix(t) for t in shock_at}
    out["shock"] = [t in shock_x for t in x]
    out["markers"] = [
        {
            "t": unix(e.at),
            "kind": MARKER_KIND[e.type],
            "label": f"{TYPE_LABEL[e.type]} · {e.detail}",
        }
        for e in events.itertuples()
    ]
    out["vendor"] = (
        {"value": int(vendor_price), "label": f"Vendor floor {fmt.coins_text(int(vendor_price))}"}
        if vendor_price
        else None
    )
    return out


def item_events(events: pd.DataFrame, names: dict[int, str], lo: date, hi: date) -> dict:
    ev = events.sort_values("at", ascending=False) if len(events) else events
    rows = [event_row(e, names) for e in ev.head(MAX_ITEM_EVENTS).itertuples()]
    out = {"sub": range_sub(lo, hi, plural(len(events), "event")), "rows": rows}
    if not rows:
        out["note"] = "No mispricings, supply shocks or buyouts in this range."
    return out
