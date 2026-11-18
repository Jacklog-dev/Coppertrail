"""Payloads for the Patterns view (HANDOVER 8b "Views", mock-ups PatternsRhythm, PatternsSpreads).

Pure functions from a `PatternResult` (and, where a chart needs raw series, the job's
`Context`) to JSON-able dicts. The front end knows no job: it gets a generic table
(columns with a `kind`, preformatted cells) and generic charts. Spec:
`docs/superpowers/specs/2026-11-17-patterns-movers-views.md`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from coppertrail.patterns import REGISTRY, Context, PatternResult
from coppertrail.patterns.common import daily_prices
from coppertrail.ui import format as fmt
from coppertrail.ui.viewdata import (
    MARKER_KIND,
    TYPE_LABEL,
    coin,
    finite,
    local_midnight,
    nums,
    plural,
    range_sub,
    unix,
)

MAX_ROWS = 200
CHIP = "needs data"
DEFAULT_KEY = "daily_rhythm"
BAND_COLORS = ("s1", "s2", "s3", "s4", "s5", "s6", "text2")
WORTH = 0.10  # processing spreads: "worth it" from a 10 % margin (patterns/spreads.py)
BUY_HOUR, SELL_HOUR = 21, 7  # daily rhythm windows start (patterns/rhythm.py)
CONFIDENCE_TONE = {"high": "text1", "medium": "text2", "low": "text3"}

# Short method notes for the basis line (the job's full method is the tooltip).
SHORT_METHOD = {
    "daily_rhythm": "Buy 21–24 h at lowest buyout · sell 07–10 h · 5 % cut deducted",
    "weekday_reset": "Price and supply by weekday · 100 = centred 7-day mean",
    "mispricings": "Min buyout 30 % below the 6 h median of p25",
    "supply_shocks": "Quantity at least double its 24 h baseline for 2 h",
    "buyouts": "Quantity −40 % and min buyout +20 % from one snapshot to the next",
    "mean_reversion": "15 % below the 7-day mean · recovery within 3 days",
    "processing_spreads": "Margin = product after 5 % cut − inputs at lowest buyout",
    "progression_wave": "Median per level band · 100 = first day",
    "correlations": "Daily residual returns · lags −3 to 3 days",
    "vendor_floor": "Hours with min buyout at or below 110 % of the vendor price",
    "build_effects": "24 h after a build against 24 h before, minus the placebo",
    "inflation": "Basket indices · 100 = first day · weighted by turnover",
}

# What each job counts in "N … checked · M … show the pattern" (noun, hit phrase).
COUNT_WORDS = {
    "processing_spreads": ("recipe", "worth it"),
}


# Jobs whose input the collector fills from 18 Nov 2026: (title, text).
WAITING = {
    "processing_spreads": (
        "Waiting for recipe data",
        "Processing spreads need the recipe list (reagents and products). The collector "
        "fetches it on every run from 18 Nov 2026; pull the latest data once it has run.",
    ),
    "vendor_floor": (
        "Waiting for vendor prices",
        "The vendor floor needs each item's vendor price. The collector backfills it, up to "
        "200 items per run, from 18 Nov 2026; pull the latest data once it has run.",
    ),
    "build_effects": (
        "Waiting for the build list",
        "Patch and build effects need the game's build feed. The collector reads it on every "
        "run from 18 Nov 2026; pull the latest data once it has run.",
    ),
}

# The input exists in the archive, but not in the date range or the item filter.
NO_BUILDS_IN_RANGE = "No builds in this date range."
NO_VENDOR_IN_FILTER = "No vendor prices for the items in this filter yet."


# Tabs and basis ------------------------------------------------------------------------


def ordered_specs():
    return sorted(REGISTRY.values(), key=lambda s: s.number)


def tabs(days: int, waiting: set[str]) -> list[dict]:
    """Every registered job by number; "needs data" when too short or its input is empty."""
    return [
        {
            "key": s.key,
            "title": s.title,
            "number": s.number,
            "chip": CHIP if days < s.min_days or s.key in waiting else None,
        }
        for s in ordered_specs()
    ]


def basis(result: PatternResult) -> dict:
    noun, hit = COUNT_WORDS.get(result.key, ("item", ""))
    n = result.items_hit
    hits = f"{plural(n, noun)} {hit or ('shows' if n == 1 else 'show') + ' the pattern'}"
    span = (
        f" ({fmt.date_range(result.first_day, result.last_day)})"
        if result.first_day and result.last_day
        else ""
    )
    return {
        "lead": f"Rests on {plural(result.days_used, 'day')}",
        "text": (f" of data{span} · {plural(result.items_checked, noun)} checked · {hits}"),
        "method": SHORT_METHOD.get(result.key, ""),
        "detail": result.method,
    }


# Table ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Col:
    label: str
    kind: str  # rank, item, text, muted, num, change, coin, bar, level
    cell: Callable[[pd.Series], object] | None = None

    @property
    def num(self) -> bool:
        return self.kind in ("num", "change", "coin", "bar")


@dataclass(frozen=True)
class Sort:
    key: str
    label: str
    by: str | None = None  # column; None = the job's order
    ascending: bool = False


STRONGEST = Sort("strongest", "strongest")
BY_NAME = Sort("name", "name", "name", True)
BY_SALES = Sort("sales", "sales/day", "sales_per_day")


def _v(row: pd.Series, col: str):
    v = row.get(col)
    return v if finite(v) else None


def change_cell(col: str) -> Callable[[pd.Series], object]:
    return lambda r: fmt.change(_v(r, col))


def count_cell(col: str) -> Callable[[pd.Series], object]:
    return lambda r: fmt.count(_v(r, col)) if _v(r, col) is not None else "–"


def share_cell(col: str) -> Callable[[pd.Series], object]:
    return lambda r: fmt.whole_share(_v(r, col)) if _v(r, col) is not None else "–"


def signed_coin(copper) -> dict | None:
    """A coin dict that may be negative (margins): `neg` makes the front end print a minus."""
    if not finite(copper):
        return None
    c = int(round(float(copper)))
    out = coin(abs(c))
    out["text"] = fmt.signed_coins_text(c)
    if c < 0:
        out["neg"] = True
    return out


def item_cell(row: pd.Series) -> dict:
    return {"name": str(row["name"])}


def bar(share, text: str, color: str = "rise") -> dict:
    return {"share": round(float(share), 4) if finite(share) else 0.0, "text": text, "color": color}


def day_text(d) -> str:
    if d is None or (isinstance(d, float) and np.isnan(d)) or pd.isna(d):
        return "–"
    return fmt.day_month(pd.Timestamp(d).date())


SALES = Col("Sales/day", "num", count_cell("sales_per_day"))


@dataclass(frozen=True)
class Table:
    title: str
    cols: tuple[Col, ...]
    sorts: tuple[Sort, ...] = (STRONGEST, BY_SALES, BY_NAME)
    row_id: Callable[[pd.Series], object] = lambda r: int(r["item_id"])


def sort_frame(ranked: pd.DataFrame, table: Table, sort: str | None) -> tuple[pd.DataFrame, str]:
    chosen = next((s for s in table.sorts if s.key == sort), table.sorts[0])
    if chosen.by is None or chosen.by not in ranked.columns:
        return ranked.reset_index(drop=True), chosen.key
    key = (lambda s: s.str.casefold()) if chosen.by == "name" else None
    out = ranked.sort_values(
        chosen.by, ascending=chosen.ascending, na_position="last", kind="stable", key=key
    )
    return out.reset_index(drop=True), chosen.key


def table_payload(
    ranked: pd.DataFrame, table: Table, sort: str | None, selected
) -> tuple[dict, pd.DataFrame]:
    rows, sort_key = sort_frame(ranked, table, sort)
    head = rows.head(MAX_ROWS)
    out_rows = []
    for i, r in head.iterrows():
        cells = []
        for c in table.cols:
            cells.append(str(i + 1) if c.kind == "rank" else c.cell(r))
        out_rows.append({"id": table.row_id(r), "item": int(r["item_id"]), "cells": cells})
    payload = {
        "title": table.title,
        "sorts": [{"key": s.key, "label": s.label} for s in table.sorts],
        "sort": sort_key,
        "columns": [{"label": c.label, "kind": c.kind, "num": c.num} for c in table.cols],
        "rows": out_rows,
        "selected": selected,
        "more": f"first {MAX_ROWS} of {fmt.thousands(len(rows))} shown"
        if len(rows) > MAX_ROWS
        else "",
    }
    if not out_rows:
        payload["note"] = "No rows in this filter."
    return payload, rows


RANK = Col("#", "rank")
ITEM = Col("Item", "item", item_cell)


def _rhythm_bar(r):
    return bar(r["wins"] / r["nights"] if r["nights"] else 0, f"{r['wins']} / {r['nights']}")


def _confidence(r):
    c = str(r.get("confidence") or "low")
    return {"text": c, "tone": CONFIDENCE_TONE.get(c, "text3")}


def _ratio_line(r) -> str:
    return str(r.get("ratio") or r.get("recipe") or "").replace(" x ", " × ").replace("->", "→")


def _recipe_cell(r):
    sub = " · ".join(
        p for p in (r.get("profession"), "Leather chain" if r.get("chain") else "") if p
    )
    return {"name": _ratio_line(r), "sub": sub}


def _pair_cell(r):
    lag = int(r["lag_days"]) if finite(r.get("lag_days")) else 0
    follows = "moves the same day" if lag == 0 else f"follows after {plural(lag, 'day')}"
    return {"name": str(r["name"]), "sub": f"{r['partner_name']} {follows}"}


def _ratio_cell(col):
    return lambda r: fmt.ratio(_v(r, col)) if _v(r, col) is not None else "–"


def _pts_cell(col, scale=100.0):
    return lambda r: fmt.points(_v(r, col) * scale) if _v(r, col) is not None else "–"


TABLES: dict[str, Table] = {
    "daily_rhythm": Table(
        "Items ranked by reliability",
        (
            RANK,
            ITEM,
            Col("Wins / nights tested", "bar", _rhythm_bar),
            Col("Avg result", "change", change_cell("avg_result")),
            SALES,
            Col("Confidence", "level", _confidence),
        ),
        (
            STRONGEST,
            Sort("wins", "win rate", "win_rate"),
            Sort("result", "avg result", "avg_result"),
            BY_SALES,
            BY_NAME,
        ),
    ),
    "weekday_reset": Table(
        "Items ranked by weekday swing",
        (
            RANK,
            ITEM,
            Col("Peak", "text", lambda r: str(r.get("peak_day") or "–")),
            Col("Trough", "muted", lambda r: str(r.get("trough_day") or "–")),
            Col("Swing", "num", share_cell("amplitude")),
            Col(
                "Weeks it held",
                "bar",
                lambda r: bar(
                    _v(r, "consistency") or 0, fmt.whole_share(_v(r, "consistency") or 0)
                ),
            ),
            Col("Reset", "change", change_cell("reset_change")),
        ),
        (
            STRONGEST,
            Sort("swing", "swing", "amplitude"),
            Sort("reset", "reset change", "reset_change"),
            BY_NAME,
        ),
    ),
    "mispricings": Table(
        "Items ranked by mispricings",
        (
            RANK,
            ITEM,
            Col("Events", "num", count_cell("events")),
            Col("Median depth", "change", change_cell("median_depth")),
            Col(
                "Back after",
                "num",
                lambda r: (
                    fmt.minutes(_v(r, "median_minutes_to_correct"))
                    if _v(r, "median_minutes_to_correct") is not None
                    else "–"
                ),
            ),
            Col("Corrected", "num", share_cell("corrected_share")),
            SALES,
        ),
        (
            STRONGEST,
            Sort("events", "events", "events"),
            Sort("depth", "deepest", "deepest", True),
            BY_SALES,
            BY_NAME,
        ),
    ),
    "supply_shocks": Table(
        "Items ranked by shock response",
        (
            RANK,
            ITEM,
            Col("Shocks", "num", count_cell("shocks")),
            Col("Jump", "change", change_cell("median_jump")),
            Col("Price after", "change", change_cell("median_price_change")),
            Col(
                "Lag",
                "num",
                lambda r: (
                    f"{int(_v(r, 'median_lag_hours'))} h"
                    if _v(r, "median_lag_hours") is not None
                    else "–"
                ),
            ),
            Col("Fell after", "num", share_cell("price_fell_share")),
            SALES,
        ),
        (
            STRONGEST,
            Sort("shocks", "shocks", "shocks"),
            Sort("price", "price after", "median_price_change", True),
            BY_SALES,
            BY_NAME,
        ),
    ),
    "buyouts": Table(
        "Items ranked by buyouts",
        (
            RANK,
            ITEM,
            Col("Buyouts", "num", count_cell("buyouts")),
            Col("Quantity", "change", change_cell("median_quantity_drop")),
            Col("Min buyout", "change", change_cell("median_min_jump")),
            Col(
                "Reset after",
                "num",
                lambda r: (
                    fmt.minutes(_v(r, "median_minutes_to_reset"))
                    if _v(r, "median_minutes_to_reset") is not None
                    else "–"
                ),
            ),
            SALES,
        ),
        (
            STRONGEST,
            Sort("buyouts", "buyouts", "buyouts"),
            Sort("jump", "min jump", "median_min_jump"),
            BY_SALES,
            BY_NAME,
        ),
    ),
    "mean_reversion": Table(
        "Items ranked by recovery edge",
        (
            RANK,
            ITEM,
            Col(
                "Recovered / signals",
                "bar",
                lambda r: bar(
                    _v(r, "hit_rate") or 0,
                    f"{int(r.get('recovered') or 0)} / {int(r.get('signals') or 0)}",
                ),
            ),
            Col("Base rate", "num", share_cell("base_rate")),
            Col("Edge", "num", _pts_cell("edge")),
            Col("3-day return", "change", change_cell("median_return")),
        ),
        (STRONGEST, Sort("edge", "edge", "edge"), Sort("signals", "signals", "signals"), BY_NAME),
    ),
    "processing_spreads": Table(
        "Recipes ranked by margin now",
        (
            RANK,
            Col("Recipe", "item", _recipe_cell),
            Col("Margin now", "coin", lambda r: signed_coin(_v(r, "margin_now"))),
            Col("30 d mean", "coin", lambda r: signed_coin(_v(r, "mean_margin_30d"))),
            Col(
                "Days worth it",
                "bar",
                lambda r: bar(
                    _v(r, "worth_share") or 0,
                    f"{int(r.get('days_worth') or 0)} / {int(r.get('days_priced') or 0)}",
                ),
            ),
        ),
        (
            STRONGEST,
            Sort("margin", "margin now", "margin_now"),
            Sort("pct", "margin %", "margin_pct_now"),
            Sort("worth", "days worth it", "worth_share"),
            BY_NAME,
        ),
        row_id=lambda r: int(r["spell_id"]),
    ),
    "progression_wave": Table(
        "Items ranked by supply growth",
        (
            RANK,
            ITEM,
            Col("Band", "muted", lambda r: str(r.get("band") or "–")),
            Col("Price", "change", change_cell("price_change")),
            Col("Supply", "change", change_cell("supply_change")),
            Col("Turning point", "muted", lambda r: day_text(r.get("turning_day"))),
            SALES,
        ),
        (STRONGEST, Sort("price", "price change", "price_change", True), BY_SALES, BY_NAME),
    ),
    "correlations": Table(
        "Pairs ranked by correlation",
        (
            RANK,
            Col("Pair", "item", _pair_cell),
            Col(
                "Correlation",
                "num",
                lambda r: fmt.decimal(r["corr"]) if finite(r.get("corr")) else "–",
            ),
            Col("Days", "num", count_cell("n_days")),
            Col("Same group", "muted", lambda r: "yes" if r.get("same_group") else "–"),
        ),
        (STRONGEST, Sort("days", "days", "n_days"), BY_NAME),
        row_id=lambda r: f"{int(r['item_id'])}-{int(r['partner_id'])}",
    ),
    "vendor_floor": Table(
        "Items ranked by time near the floor",
        (
            RANK,
            ITEM,
            Col("Vendor price", "coin", lambda r: coin(_v(r, "vendor_price"))),
            Col("Lowest buyout", "coin", lambda r: coin(_v(r, "min_now"))),
            Col("Now", "num", _ratio_cell("ratio_now")),
            Col("Lowest", "num", _ratio_cell("lowest_ratio")),
            Col("Hours near", "num", share_cell("share_near")),
            SALES,
        ),
        (STRONGEST, Sort("now", "closest now", "ratio_now", True), BY_SALES, BY_NAME),
    ),
    "build_effects": Table(
        "Items ranked by build effect",
        (
            RANK,
            ITEM,
            Col("Build", "muted", lambda r: str(r.get("build") or "–")),
            Col("Price", "change", change_cell("price_change")),
            Col(
                "Placebo",
                "muted",
                lambda r: (
                    fmt.signed_percent(_v(r, "placebo_price"))
                    if _v(r, "placebo_price") is not None
                    else "–"
                ),
            ),
            Col("Beyond placebo", "change", change_cell("excess_price")),
            Col("Supply beyond", "change", change_cell("excess_supply")),
        ),
        (STRONGEST, Sort("excess", "beyond placebo", "excess_price"), BY_NAME),
    ),
    "inflation": Table(
        "Basket items ranked by contribution",
        (
            RANK,
            ITEM,
            Col("Group", "muted", lambda r: str(r.get("group") or "–")),
            Col("Price", "change", change_cell("price_change")),
            Col(
                "Weight",
                "num",
                lambda r: fmt.share(_v(r, "weight")) if _v(r, "weight") is not None else "–",
            ),
            Col("Contribution", "num", _pts_cell("contribution")),
            Col(
                "Fits",
                "level",
                lambda r: (
                    {"text": "fits", "tone": "text1"}
                    if r.get("fits")
                    else {"text": "no", "tone": "text3"}
                ),
            ),
        ),
        (STRONGEST, Sort("price", "price change", "price_change"), BY_NAME),
    ),
}


# Charts ----------------------------------------------------------------------------------


def chart(title: str, sub: str, **kw) -> dict:
    out = {"title": title, "sub": sub, "height": kw.pop("height", 300)}
    out.update({k: v for k, v in kw.items() if v is not None})
    return out


def note_chart(title: str, sub: str, note: str) -> dict:
    return {"title": title, "sub": sub, "note": note}


def series(label: str, color: str, values, **kw) -> dict:
    return {"label": label, "color": color, "values": values, **kw}


def split_bars(values: list, groups: list[tuple[str, str, list[bool]]]) -> list[dict]:
    """One bar series per (label, colour, mask): a bar shows in the first series that has it."""
    out = []
    for label, color, mask in groups:
        out.append(
            series(
                label,
                color,
                [v if m else None for v, m in zip(values, mask, strict=True)],
                bars=True,
            )
        )
    return out


def legend_of(items: list[dict]) -> list[dict]:
    return [{k: s[k] for k in ("label", "color", "dashed", "bars") if k in s} for s in items]


def pct(values) -> list[float | None]:
    return nums([v * 100 if finite(v) else None for v in values], 2)


def _item_rows(frame: pd.DataFrame | None, item_id: int) -> pd.DataFrame:
    if frame is None or frame.empty or "item_id" not in frame.columns:
        return pd.DataFrame()
    return frame[frame["item_id"] == item_id]


def _days(frame: pd.DataFrame, col: str = "day") -> list[int]:
    return [local_midnight(pd.Timestamp(d).date()) for d in frame[col]]


def _span(r: PatternResult, *extra: str) -> str:
    lo, hi = r.first_day, r.last_day
    if lo is None or hi is None:
        return " · ".join(e for e in extra if e)
    return range_sub(lo, hi, *extra)


def _hours_bars(
    r: PatternResult, title: str, label: str, color: str, frame: pd.DataFrame | None, sub: str
) -> dict:
    if frame is None or frame.empty or not (frame["events"] > 0).any():
        return note_chart(title, _span(r, sub), "Nothing found yet.")
    f = frame.set_index("hour").reindex(range(24)).fillna(0)
    s = [series(label, color, nums(f["events"], 0), bars=True)]
    return chart(
        title,
        _span(r, sub),
        legend=legend_of(s),
        x=list(range(24)),
        xKind="hour",
        series=s,
        y="count",
        height=190,
    )


def _markers(events: pd.DataFrame | None, item_id: int) -> list[dict]:
    ev = _item_rows(events, item_id)
    return [
        {
            "t": unix(e.at),
            "kind": MARKER_KIND[e.type],
            "label": f"{TYPE_LABEL[e.type]} · {e.detail}",
        }
        for e in ev.itertuples()
    ]


def _scan_chart(
    r: PatternResult, ctx: Context, item_id: int, name: str, extra: str, *, p25: bool
) -> dict:
    title = f"{name} — every snapshot"
    sc = _item_rows(ctx.hourly, item_id).sort_values("observed_at")
    if sc.empty:
        return note_chart(title, _span(r), "No snapshots of this item in the range.")
    first = sc["observed_at"].iloc[0].tz_convert(fmt.LOCAL_TZ).date()
    last = sc["observed_at"].iloc[-1].tz_convert(fmt.LOCAL_TZ).date()
    sub = " · ".join([fmt.date_range(first, last), plural(len(sc), "snapshot"), extra])
    s = [series("Lowest buyout", "s1", nums(sc["min"], 1), width="primary")]
    if p25:
        s.append(series("Lower quartile", "s2", nums(sc["p25"], 1)))
    return chart(
        title,
        sub,
        legend=legend_of(s),
        x=[unix(t) for t in sc["observed_at"]],
        xKind="time",
        series=s,
        markers=_markers(r.events, item_id),
        y="coins",
    )


def charts_daily_rhythm(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    item_id, name = int(row["item_id"]), str(row["name"])
    title = f"{name} — buy {fmt.hour_of_day(BUY_HOUR)}, sell {fmt.hour_of_day(SELL_HOUR)}"
    n = _item_rows(r.charts.get("nights"), item_id).sort_values("night")
    out = []
    if n.empty:
        out.append(
            note_chart(title, _span(r, "after 5 % cut"), "No nights could be tested for this item.")
        )
    else:
        values = pct(n["result"])
        won = [bool(w) for w in n["won"]]
        s = split_bars(
            values, [("Night won", "rise", won), ("Night lost", "fall", [not w for w in won])]
        )
        mean = float(n["result"].mean())
        out.append(
            chart(
                title,
                _span(r, plural(len(n), "night"), "after 5 % cut"),
                legend=[*legend_of(s), {"label": "Mean result", "color": "s1", "dashed": True}],
                x=_days(n, "night"),
                xKind="day",
                series=s,
                refLines=[
                    {
                        "value": round(mean * 100, 2),
                        "label": f"mean {fmt.signed_percent(mean)}",
                        "color": "s1",
                    }
                ],
                y="percent",
            )
        )
    td = _item_rows(r.charts.get("typical_day"), item_id).set_index("hour").reindex(range(24))
    sub = _span(r, "100 = daily mean")
    if td["min_idx"].isna().all():
        out.append(note_chart("Typical day", sub, "No hourly profile for this item."))
    else:
        s = [
            series("Lowest buyout", "s1", nums(td["min_idx"], 2), width="primary"),
            series("Supply", "s2", nums(td["quantity_idx"], 2)),
        ]
        out.append(
            chart(
                "Typical day",
                sub,
                legend=legend_of(s),
                x=list(range(24)),
                xKind="hour",
                series=s,
                refLines=[{"value": 100}],
                vLines=[
                    {"x": BUY_HOUR, "label": "buy", "color": "rise"},
                    {"x": SELL_HOUR, "label": "sell", "color": "fall"},
                ],
                y="index",
                height=190,
            )
        )
    return out


def charts_weekday(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    def week_chart(title, frame, sub):
        if frame is None or frame.empty:
            return note_chart(title, sub, "No weekday profile yet.")
        f = frame.sort_values("weekday")
        s = [
            series("Price", "s1", nums(f["price_idx"], 2), width="primary"),
            series("Supply", "s2", nums(f["supply_idx"], 2)),
        ]
        return chart(
            title,
            sub,
            legend=legend_of(s),
            x=list(range(len(f))),
            xKind="cat",
            xLabels=[str(d) for d in f["day_name"]],
            series=s,
            refLines=[{"value": 100}],
            y="index",
            height=240,
        )

    item_id, name = int(row["item_id"]), str(row["name"])
    return [
        week_chart(
            f"{name} — by weekday",
            _item_rows(r.charts.get("weekday"), item_id),
            _span(r, "100 = 7-day mean"),
        ),
        week_chart(
            "Whole selection — by weekday",
            r.charts.get("market_weekday"),
            _span(r, "trimmed mean over items"),
        ),
    ]


def charts_mispricings(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    item_id, name = int(row["item_id"]), str(row["name"])
    return [
        _scan_chart(r, ctx, item_id, name, "mispricings marked", p25=True),
        _hours_bars(
            r,
            "Mispricings by hour of day",
            "Mispricings",
            "s4",
            r.charts.get("by_hour"),
            "all items, local time",
        ),
    ]


def charts_buyouts(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    item_id, name = int(row["item_id"]), str(row["name"])
    return [
        _scan_chart(r, ctx, item_id, name, "buyouts marked", p25=False),
        _hours_bars(
            r,
            "Buyouts by hour of day",
            "Buyouts",
            "s2",
            r.charts.get("by_hour"),
            "all items, local time",
        ),
    ]


def charts_supply_shocks(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    item_id, name = int(row["item_id"]), str(row["name"])
    title = f"{name} — listed quantity"
    h = _item_rows(ctx.hourly, item_id).sort_values("hour")
    out = []
    if h.empty:
        out.append(note_chart(title, _span(r), "No hourly data for this item."))
    else:
        ev = _item_rows(r.charts.get("events"), item_id)
        shock_hours: set[int] = set()
        for e in ev.itertuples():
            start = pd.Timestamp(e.at)
            for k in range(int(e.hours) if finite(e.hours) else 1):
                shock_hours.add(unix(start + pd.Timedelta(hours=k)))
        x = [unix(t) for t in h["hour"]]
        mask = [t in shock_hours for t in x]
        values = nums(h["quantity"], 0)
        s = split_bars(
            values, [("Listed quantity", "s6", [not m for m in mask]), ("Supply shock", "s3", mask)]
        )
        out.append(
            chart(
                title,
                _span(r, plural(len(ev), "shock")),
                legend=legend_of(s),
                x=x,
                xKind="time",
                series=s,
                y="count",
            )
        )
    resp = _item_rows(r.charts.get("response"), item_id).sort_values("lag")
    allr = r.charts.get("response_all")
    sub = _span(r, "min buyout against its prior 24 h median")
    if allr is None or allr.empty:
        out.append(note_chart("Price after a shock", sub, "No shocks found yet."))
    else:
        allr = allr.sort_values("lag")
        lags = [int(v) for v in allr["lag"]]
        item_vals = (
            resp.set_index("lag")["price_change"].reindex(lags)
            if len(resp)
            else pd.Series([np.nan] * len(lags))
        )
        s = [
            series(name, "s1", pct(item_vals), width="primary"),
            series("All shocks", "s2", pct(allr["price_change"])),
        ]
        out.append(
            chart(
                "Price after a shock",
                sub,
                legend=legend_of(s),
                x=lags,
                xKind="num",
                xSuffix=" h",
                series=s,
                refLines=[{"value": 0}],
                y="percent",
                height=190,
            )
        )
    return out


def charts_mean_reversion(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    item_id, name = int(row["item_id"]), str(row["name"])
    title = f"{name} — price against its 7-day mean"
    f = _item_rows(r.charts.get("series"), item_id).sort_values("day")
    if f.empty:
        return [note_chart(title, _span(r), "No daily prices for this item.")]
    sig = _item_rows(r.charts.get("signals"), item_id)
    s = [
        series("Price", "s1", nums(f["price"], 1), width="primary"),
        series("7-day mean", "s2", nums(f["mean7"], 1)),
        series("Signal line (−15 %)", "text3", nums(f["threshold"], 1), dash=True),
    ]
    labels = [
        {
            "x": local_midnight(pd.Timestamp(e.day).date()),
            "y": float(e.price),
            "text": "recovered" if e.recovered else "signal",
            "color": "rise" if e.recovered else "fall",
            "below": True,
        }
        for e in sig.itertuples()
        if finite(e.price)
    ]
    out = [
        chart(
            title,
            _span(r, plural(len(sig), "signal")),
            legend=[*legend_of(s[:2]), {"label": s[2]["label"], "color": "text3", "dashed": True}],
            x=_days(f),
            xKind="day",
            series=s,
            labels=labels,
            y="coins",
        )
    ]
    if len(sig):
        sig = sig.sort_values("day")
        values = pct(sig["ret"])
        up = [finite(v) and v > 0 for v in sig["ret"]]
        bars = split_bars(values, [("Gain", "rise", up), ("Loss", "fall", [not u for u in up])])
        out.append(
            chart(
                "Return 3 days after each signal",
                _span(r, "after 5 % cut"),
                legend=legend_of(bars),
                x=_days(sig),
                xKind="day",
                series=bars,
                refLines=[{"value": 0}],
                y="percent",
                height=190,
            )
        )
    return out


def charts_spreads(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    spell = int(row["spell_id"])
    recipe = str(row.get("recipe") or row["name"])
    title = f"{recipe} vs input cost"
    sp = r.charts.get("spread")
    sp = (
        sp[sp["spell_id"] == spell].sort_values("day")
        if sp is not None and len(sp)
        else pd.DataFrame()
    )
    if sp.empty:
        return [
            note_chart(
                title,
                _span(r),
                "No day with every reagent priced; the margin uses the latest snapshot only.",
            )
        ]
    s = [
        series(recipe, "s1", nums(sp["value"], 0), width="primary"),
        series(f"Input cost: {_ratio_line(row).split(' → ')[0]}", "s2", nums(sp["cost"], 0)),
    ]
    x = _days(sp)
    margin_text = [
        fmt.signed_coins_text(int(round(m))) if finite(m) else None for m in sp["margin"]
    ]
    out = [
        chart(
            title,
            _span(r, "after 5 % cut"),
            legend=[*legend_of(s), {"label": "Margin", "color": "s1", "bars": True}],
            x=x,
            xKind="day",
            series=s,
            bands=[{"upper": 0, "lower": 1, "color": "s1"}],
            tipExtra=[{"label": "Margin", "values": margin_text}],
            y="coins",
        )
    ]
    dm = r.charts.get("daily_margin")
    dm = (
        dm[dm["spell_id"] == spell].sort_values("day")
        if dm is not None and len(dm)
        else pd.DataFrame()
    )
    if len(dm):
        values = nums(dm["margin"], 0)
        p = dm["margin_pct"].astype("float64")
        worth = [bool(v >= WORTH) for v in p]
        loss = [bool(v < 0) for v in p]
        thin = [not w and not lo_ for w, lo_ in zip(worth, loss, strict=True)]
        bars = split_bars(
            values, [("Worth it", "rise", worth), ("Thin", "s6", thin), ("Loss", "fall", loss)]
        )
        line = WORTH * float(sp["cost"].median())
        out.append(
            chart(
                "Daily margin",
                _span(r, f"worth it from {fmt.whole_share(WORTH)} of the input cost"),
                legend=legend_of(bars),
                x=_days(dm),
                xKind="day",
                series=bars,
                refLines=[{"value": round(line), "label": "worth it"}],
                y="coins",
                height=190,
            )
        )
    return out


def _band_chart(r: PatternResult, title: str, col: str, band: str | None, turn) -> dict:
    b = r.charts.get("bands")
    sub = _span(r, "median per level band · 100 = first day")
    if b is None or b.empty:
        return note_chart(title, sub, "No level bands in this filter.")
    wide = b.pivot_table(index="day", columns="band", values=col).sort_index()
    order = sorted(wide.columns, key=lambda s: int(str(s).split("-")[0]))
    s = [
        series(
            str(bd),
            BAND_COLORS[i % len(BAND_COLORS)],
            nums(wide[bd], 2),
            width="primary" if str(bd) == band else "tertiary",
        )
        for i, bd in enumerate(order)
    ]
    v = []
    if band and turn is not None and not pd.isna(turn):
        v = [
            {
                "x": local_midnight(pd.Timestamp(turn).date()),
                "label": f"{band} turns",
                "color": "accent",
            }
        ]
    return chart(
        title,
        sub,
        legend=legend_of(s),
        x=_days(pd.DataFrame({"day": wide.index})),
        xKind="day",
        series=s,
        refLines=[{"value": 100}],
        vLines=v or None,
        y="index",
        height=240,
    )


def charts_progression(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    band = str(row.get("band")) if row is not None and row.get("band") is not None else None
    tp = r.charts.get("turning_points")
    turn = None
    if band and tp is not None and len(tp):
        hit = tp[tp["band"] == band]
        turn = hit["turning_day"].iloc[0] if len(hit) else None
    return [
        _band_chart(r, "Supply by level band", "supply_idx", band, turn),
        _band_chart(r, "Price by level band", "price_idx", band, turn),
    ]


def charts_correlations(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    a, b = int(row["item_id"]), int(row["partner_id"])
    names = (str(row["name"]), str(row["partner_name"]))
    title = f"{names[0]} and {names[1]}"
    ser = r.charts.get("series")
    if ser is None or ser.empty:
        return [note_chart(title, _span(r), "No daily prices for this pair.")]
    wide = (
        ser[ser["item_id"].isin([a, b])]
        .pivot_table(index="day", columns="item_id", values="price")
        .sort_index()
    )
    s = []
    for i, (iid, nm) in enumerate(zip((a, b), names, strict=True)):
        col = wide[iid] if iid in wide.columns else pd.Series(np.nan, index=wide.index)
        base = col.dropna().iloc[0] if col.notna().any() else np.nan
        s.append(
            series(
                nm,
                ("s1", "s2")[i],
                nums(100 * col / base, 2),
                width="primary" if i == 0 else "secondary",
            )
        )
    out = [
        chart(
            title,
            _span(r, "100 = first priced day"),
            legend=legend_of(s),
            x=_days(pd.DataFrame({"day": wide.index})),
            xKind="day",
            series=s,
            refLines=[{"value": 100}],
            y="index",
        )
    ]
    lags = r.charts.get("lags")
    lg = (
        lags[(lags["item_id"] == a) & (lags["partner_id"] == b)].sort_values("lag")
        if lags is not None and len(lags)
        else pd.DataFrame()
    )
    if len(lg):
        bs = [series("Correlation", "s1", nums(lg["corr"], 3), bars=True)]
        out.append(
            chart(
                "Correlation by lag",
                _span(r, f"positive lag: {names[1]} follows"),
                legend=legend_of(bs),
                x=[int(v) for v in lg["lag"]],
                xKind="num",
                xSuffix=" d",
                series=bs,
                refLines=[{"value": 0}],
                y="plain",
                yFromZero=False,
                height=190,
            )
        )
    return out


def charts_vendor(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    item_id, name = int(row["item_id"]), str(row["name"])
    title = f"{name} — lowest buyout and vendor price"
    h = _item_rows(r.charts.get("hours"), item_id).sort_values("hour")
    vendor = _v(row, "vendor_price")
    out = []
    if h.empty:
        out.append(
            note_chart(
                title, _span(r), "No hourly prices for this item (checked on its latest snapshot)."
            )
        )
    else:
        s = [series("Lowest buyout", "s1", nums(h["min"], 1), width="primary")]
        refs = (
            [{"value": int(vendor), "label": f"Vendor price {fmt.coins_text(int(vendor))}"}]
            if vendor
            else []
        )
        out.append(
            chart(
                title,
                _span(r),
                legend=[*legend_of(s), {"label": "Vendor price", "color": "text3", "dashed": True}],
                x=[unix(t) for t in h["hour"]],
                xKind="time",
                series=s,
                refLines=refs,
                y="coins",
            )
        )
    out.append(
        _hours_bars(
            r,
            "Hours near the floor by hour of day",
            "Hours near",
            "s5",
            r.charts.get("by_hour"),
            "all items, local time",
        )
    )
    return out


def _build_window(
    w: pd.DataFrame | None, ctx: Context, item_id: int, version: str, at: pd.Timestamp | None
) -> pd.DataFrame:
    """The hourly window of one item around one build (two builds can share a version)."""
    if w is None or w.empty:
        return pd.DataFrame()
    w = w[(w["item_id"] == item_id) & (w["version"].astype(str) == version)]
    if at is not None and "published_at" in w:
        w = w[pd.to_datetime(w["published_at"], utc=True) == at]
    return w.sort_values("offset_h")


def charts_builds(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    item_id, name = int(row["item_id"]), str(row["name"])
    version = str(row.get("build") or "")
    title = f"{name} — around build {version}".strip()
    at = pd.Timestamp(row.get("published_at")) if pd.notna(row.get("published_at")) else None
    w = _build_window(r.charts.get("window"), ctx, item_id, version, at)
    out = []
    if w.empty:
        out.append(note_chart(title, _span(r), "No hourly window around this build."))
    else:
        s = [
            series("Price", "s1", nums(w["price_idx"], 2), width="primary"),
            series("Supply", "s2", nums(w["supply_idx"], 2)),
        ]
        out.append(
            chart(
                title,
                _span(r, "100 = mean before the build"),
                legend=legend_of(s),
                x=[int(v) for v in w["offset_h"]],
                xKind="num",
                xSuffix=" h",
                series=s,
                refLines=[{"value": 100}],
                vLines=[{"x": 0, "label": f"build {version}", "color": "accent"}],
                y="index",
            )
        )
    g = r.charts.get("groups")
    if g is not None and len(g):
        g = g[g["version"].astype(str) == version]
        if at is not None and "published_at" in g:
            g = g[pd.to_datetime(g["published_at"], utc=True) == at]
    else:
        g = pd.DataFrame()
    if len(g):
        bs = [series("Price beyond placebo", "s1", pct(g["median_excess_price"]), bars=True)]
        out.append(
            chart(
                "By group",
                _span(r, f"build {version} · median per group"),
                legend=legend_of(bs),
                x=list(range(len(g))),
                xKind="cat",
                xLabels=[str(n) for n in g["group"]],
                series=bs,
                refLines=[{"value": 0}],
                y="percent",
                yFromZero=False,
                height=190,
            )
        )
    return out


def charts_inflation(r: PatternResult, ctx: Context, row: pd.Series | None) -> list[dict]:
    idx = r.charts.get("index")
    sub = _span(r, "100 = first day")
    out = []
    if idx is None or idx.empty:
        out.append(note_chart("Price index by basket", sub, "No basket items in this filter."))
    else:
        wide = idx.pivot(index="day", columns="group", values="index").sort_index()
        days = list(wide.index)
        s = []
        for group, label, color in (
            ("scarce", "Scarce goods", "s1"),
            ("farmable", "Farmable goods", "s2"),
            ("vendor", "Vendor-tied goods", "s3"),
        ):
            if group in wide.columns:
                s.append(
                    series(
                        label,
                        color,
                        nums(wide[group], 2),
                        width="primary" if group == "scarce" else "secondary",
                        fill=group == "scarce",
                    )
                )
        if row is not None:
            own = _own_index(ctx, int(row["item_id"]), days)
            if own is not None:
                s.append(series(str(row["name"]), "s4", own, width="tertiary"))
        out.append(
            chart(
                "Price index by basket",
                sub,
                legend=legend_of(s),
                x=[local_midnight(d) for d in days],
                xKind="day",
                series=s,
                refLines=[{"value": 100}],
                y="index",
            )
        )
    div = r.charts.get("divergence")
    if div is not None and len(div):
        div = div.sort_values("day")
        bs = [series("Scarce minus farmable", "s1", nums(div["divergence"], 2), bars=True)]
        out.append(
            chart(
                "Divergence",
                _span(r, "index points"),
                legend=legend_of(bs),
                x=_days(div),
                xKind="day",
                series=bs,
                refLines=[{"value": 0}],
                y="points",
                yFromZero=False,
                height=190,
            )
        )
    return out


def _own_index(ctx: Context, item_id: int, days: list[date]) -> list[float | None] | None:
    d = daily_prices(_item_rows(ctx.hourly, item_id))
    if d.empty:
        return None
    p = d.set_index("day")["price"].reindex(days).astype("float64")
    base = p.dropna()
    if base.empty or base.iloc[0] <= 0:
        return None
    return nums(100 * p / base.iloc[0], 2)


CHARTS: dict[str, Callable[[PatternResult, Context, pd.Series | None], list[dict]]] = {
    "daily_rhythm": charts_daily_rhythm,
    "weekday_reset": charts_weekday,
    "mispricings": charts_mispricings,
    "supply_shocks": charts_supply_shocks,
    "buyouts": charts_buyouts,
    "mean_reversion": charts_mean_reversion,
    "processing_spreads": charts_spreads,
    "progression_wave": charts_progression,
    "correlations": charts_correlations,
    "vendor_floor": charts_vendor,
    "build_effects": charts_builds,
    "inflation": charts_inflation,
}


# The whole pattern payload -------------------------------------------------------------


def _pick(rows: pd.DataFrame, table: Table, select, item) -> pd.Series | None:
    if rows.empty:
        return None
    if select is not None:
        for _, r in rows.iterrows():
            if str(table.row_id(r)) == str(select):
                return r
    if item is not None:
        hit = rows[rows["item_id"] == int(item)]
        if len(hit):
            return hit.iloc[0]
    return rows.iloc[0]


def build(result: PatternResult, ctx: Context, *, select, item, sort) -> dict:
    """Table and charts of a ready result; the selected row drives the charts."""
    table = TABLES[result.key]
    ranked = result.ranked if result.ranked is not None else pd.DataFrame()
    if ranked.empty or "item_id" not in ranked.columns:
        payload, _ = table_payload(pd.DataFrame(columns=["item_id", "name"]), table, sort, None)
        payload["note"] = "Nothing in this filter shows the pattern yet."
        return {"table": payload, "charts": []}
    payload, rows = table_payload(ranked, table, sort, None)
    row = _pick(rows, table, select, item)
    selected = table.row_id(row)
    payload["selected"] = selected
    # A selected row beyond the first MAX_ROWS stays listed (Item detail's "Show in patterns").
    if not any(r["id"] == selected for r in payload["rows"]):
        pos = next(i for i, r in rows.iterrows() if table.row_id(r) == selected)
        extra, _ = table_payload(rows.iloc[[pos]], table, "strongest", None)
        extra["rows"][0]["cells"][0] = str(pos + 1)
        payload["rows"].append(extra["rows"][0])
    return {"table": payload, "charts": CHARTS[result.key](result, ctx, row)}
