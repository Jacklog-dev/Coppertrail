"""Patterns view payloads (coppertrail/ui/patternview.py and Bridge.patterns)."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
from pattern_fixtures import make_ctx
from test_bridge_views import market  # noqa: F401 - shared fixture

from coppertrail.patterns import REGISTRY
from coppertrail.patterns.base import PatternResult, events_frame
from coppertrail.ui import patternview as pv
from coppertrail.ui.bridge import Bridge

LO, HI = date(2026, 11, 9), date(2026, 11, 16)


def NOW():  # noqa: N802
    return datetime(2026, 11, 17, 9, tzinfo=UTC)


def _result(key, ranked, charts=None, **kw):
    spec = REGISTRY[key]
    return PatternResult(
        ranked=ranked,
        charts=charts or {},
        key=key,
        title=spec.title,
        method=spec.method,
        days_used=8,
        first_day=LO,
        last_day=HI,
        items_checked=kw.pop("checked", 10),
        items_hit=kw.pop("hit", 2),
        **kw,
    )


def _rhythm():
    ranked = pd.DataFrame(
        [
            {"item_id": 1, "name": "Rugged Leather", "wins": 5, "nights": 6, "win_rate": 5 / 6,
             "avg_result": 0.068, "median_result": 0.05, "sales_per_day": 9063.0,
             "cheapest_hour": 23, "dearest_hour": 7, "confidence": "medium"},
            {"item_id": 2, "name": "Gold Ore", "wins": 2, "nights": 6, "win_rate": 1 / 3,
             "avg_result": -0.019, "median_result": -0.01, "sales_per_day": 1951.0,
             "cheapest_hour": 22, "dearest_hour": 8, "confidence": "low"},
        ]
    )  # fmt: skip
    nights = pd.DataFrame(
        {
            "item_id": [1, 1, 1],
            "night": [date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)],
            "buy": [1.0, 1.0, 1.0],
            "sell": [1.1, 0.9, 1.2],
            "raw_result": [0.1, -0.1, 0.2],
            "result": [0.1, -0.05, 0.15],
            "won": [True, False, True],
        }
    )
    typical = pd.DataFrame(
        {
            "item_id": [1] * 24,
            "hour": range(24),
            "min_idx": [100.0 + h for h in range(24)],
            "p25_idx": [100.0] * 24,
            "quantity_idx": [100.0 - h for h in range(24)],
        }
    )
    return _result("daily_rhythm", ranked, {"nights": nights, "typical_day": typical}, hit=1)


def test_tabs_cover_every_job_in_order():
    tabs = pv.tabs(days=8, waiting=set())
    assert [t["number"] for t in tabs] == sorted(s.number for s in REGISTRY.values())
    assert len(tabs) == 12
    chips = {t["key"]: t["chip"] for t in tabs}
    assert chips["daily_rhythm"] is None
    assert chips["weekday_reset"] == "needs data"  # 28 days
    assert pv.tabs(days=8, waiting={"vendor_floor"})[9]["chip"] == "needs data"


def test_basis_line():
    b = pv.basis(_rhythm())
    assert b["lead"] == "Rests on 8 days"
    assert (
        b["text"] == " of data (9 Nov – 16 Nov 2026) · 10 items checked · 1 item shows the pattern"
    )
    assert b["method"].startswith("Buy")
    assert b["detail"] == REGISTRY["daily_rhythm"].method


def test_daily_rhythm_payload():
    p = pv.build(_rhythm(), make_ctx(), select=None, item=None, sort=None)
    t = p["table"]
    assert t["title"] == "Items ranked by reliability"
    assert [c["label"] for c in t["columns"]] == [
        "#", "Item", "Wins / nights tested", "Avg result", "Sales/day", "Confidence"
    ]  # fmt: skip
    first = t["rows"][0]
    assert first["id"] == 1 and first["item"] == 1 and t["selected"] == 1
    assert first["cells"][2] == {"share": 0.8333, "text": "5 / 6", "color": "rise"}
    assert first["cells"][3] == {"text": "▲ +6.8 %", "dir": "rise"}
    assert first["cells"][5] == {"text": "medium", "tone": "text2"}
    nights, typical = p["charts"]
    assert nights["title"] == "Rugged Leather — buy 21:00, sell 07:00"
    assert nights["sub"] == "9 Nov – 16 Nov 2026 · 8 d · 3 nights · after 5 % cut"
    won, lost = nights["series"]
    assert won["values"] == [10.0, None, 15.0] and lost["values"] == [None, -5.0, None]
    assert won["color"] == "rise" and lost["color"] == "fall" and won["bars"]
    assert nights["refLines"][0]["color"] == "s1"
    assert nights["refLines"][0]["label"] == "mean +6.7 %"
    assert typical["xKind"] == "hour" and [v["label"] for v in typical["vLines"]] == ["buy", "sell"]


def test_selection_and_sort():
    r = _rhythm()
    p = pv.build(r, make_ctx(), select=None, item=2, sort=None)
    assert p["table"]["selected"] == 2
    assert p["charts"][0]["note"]  # no nights for item 2 in the frame
    p = pv.build(r, make_ctx(), select=None, item=None, sort="name")
    assert [row["item"] for row in p["table"]["rows"]] == [2, 1]
    assert p["table"]["sort"] == "name"
    assert pv.build(r, make_ctx(), select=None, item=None, sort="bogus")["table"]["sort"] == (
        "strongest"
    )


def test_spreads_rows_by_recipe_with_signed_coins():
    ranked = pd.DataFrame(
        [
            {"item_id": 15564, "name": "Rugged Armor Kit", "spell_id": 19058,
             "recipe": "Rugged Armor Kit", "profession": "Leatherworking",
             "ratio": "5 x Rugged Leather -> 1 Rugged Armor Kit", "chain": True,
             "value_now": 9000.0, "cost_now": 10_000.0, "margin_now": -1000.0,
             "margin_pct_now": -0.1, "mean_margin_30d": 3120.0, "mean_pct_30d": 0.3,
             "days_priced": 3, "days_worth": 2, "worth_share": 2 / 3, "sales_per_day": 8.0},
        ]
    )  # fmt: skip
    days = [date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16)]
    spread = pd.DataFrame(
        {
            "spell_id": [19058] * 3,
            "item_id": [15564] * 3,
            "day": days,
            "value": [13_000.0, 10_400.0, 9000.0],
            "cost": [10_000.0] * 3,
            "margin": [3000.0, 400.0, -1000.0],
        }
    )
    daily = spread.assign(margin_pct=spread["margin"] / spread["cost"]).drop(
        columns=["value", "cost"]
    )
    daily["worth"] = daily["margin_pct"] >= 0.1
    r = _result("processing_spreads", ranked, {"spread": spread, "daily_margin": daily})
    p = pv.build(r, make_ctx(), select=None, item=None, sort=None)
    row = p["table"]["rows"][0]
    assert row["id"] == 19058 and row["item"] == 15564
    assert row["cells"][1]["name"] == "5 × Rugged Leather → 1 Rugged Armor Kit"
    assert row["cells"][2]["neg"] and row["cells"][2]["text"] == "−10s"
    assert row["cells"][4]["text"] == "2 / 3"
    value, margin = p["charts"]
    assert value["bands"] == [{"upper": 0, "lower": 1, "color": "s1"}]
    assert value["y"] == "coins"
    worth, thin, loss = margin["series"]
    assert worth["values"] == [3000.0, None, None]
    assert thin["values"] == [None, 400.0, None]
    assert loss["values"] == [None, None, -1000.0]


def test_events_jobs_chart_scans_with_markers():
    t = datetime(2026, 11, 16, 10, tzinfo=UTC)
    scans = pd.DataFrame(
        {
            "item_id": [1, 1, 1],
            "observed_at": [t, t + timedelta(minutes=30), t + timedelta(minutes=60)],
            "min": [100.0, 40.0, 100.0],
            "p25": [110.0, 110.0, 110.0],
            "median": [120.0] * 3,
            "p75": [130.0] * 3,
            "quantity": [50, 40, 50],
            "auctions": [5, 5, 5],
            "source": ["api"] * 3,
        }
    )
    ev = events_frame(
        [
            {
                "item_id": 1,
                "at": t + timedelta(minutes=30),
                "type": "mispricing",
                "detail": "min −64 %",
                "magnitude": -0.64,
            }
        ]
    )
    ranked = pd.DataFrame(
        [
            {"item_id": 1, "name": "Mystery Meat", "events": 1, "median_depth": -0.64,
             "deepest": -0.64, "median_minutes_to_correct": 30.0, "corrected_share": 1.0,
             "sales_per_day": 800.0},
        ]
    )  # fmt: skip
    by_hour = pd.DataFrame({"hour": range(24), "events": [0] * 11 + [1] + [0] * 12})
    r = _result("mispricings", ranked, {"by_hour": by_hour}, events=ev)
    p = pv.build(r, make_ctx(scans=scans), select=None, item=None, sort=None)
    scan_chart, hours = p["charts"]
    assert scan_chart["markers"] == [
        {"t": int((t + timedelta(minutes=30)).timestamp()), "kind": "mispricing",
         "label": "Mispricing · min −64 %"}
    ]  # fmt: skip
    assert scan_chart["series"][0]["values"] == [100.0, 40.0, 100.0]
    assert hours["xKind"] == "hour" and hours["series"][0]["bars"]
    assert p["table"]["rows"][0]["cells"][5] == "30 min"


def test_bridge_patterns_states(market, config_dir):  # noqa: F811
    b = Bridge(market, now=NOW)
    p = b.patterns()
    assert p["key"] == "daily_rhythm" and p["state"] == "ready"
    assert len(p["tabs"]) == 12
    assert p["basis"]["lead"] == "Rests on 8 days"
    assert b.patterns() is p  # cached
    gap = b.patterns("weekday_reset")
    assert gap["state"] == "history"
    assert gap["gap"]["title"] == "Needs 3 more weeks of data"
    assert gap["gap"]["ready"] == "ready around 6 Dec 2026"
    wait = b.patterns("processing_spreads")
    assert wait["state"] == "waiting" and "recipe" in wait["waiting"]["title"].lower()
    chips = {t["key"]: t["chip"] for t in p["tabs"]}
    assert chips["processing_spreads"] == "needs data" and chips["build_effects"] == "needs data"
    assert chips["daily_rhythm"] is None


def test_bridge_patterns_selects_item_from_item_detail(market, config_dir):  # noqa: F811
    p = Bridge(market, now=NOW).patterns("daily_rhythm", item=8170)
    assert p["table"]["selected"] == 8170
    assert p["charts"][0]["title"].startswith("Rugged Leather")
