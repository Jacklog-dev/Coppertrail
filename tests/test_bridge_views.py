"""Bridge payloads for the Market overview and Item detail views."""

import threading
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from coppertrail.collector.legacy.store import TABLES, Store, to_arrow
from coppertrail.patterns.base import PatternResult, events_frame
from coppertrail.query.catalog import Item
from coppertrail.query.groups import load_groups
from coppertrail.ui import viewdata as vd
from coppertrail.ui.app import js_facade
from coppertrail.ui.bridge import Bridge, Memo, item_details


def NOW():  # noqa: N802
    return datetime(2026, 11, 17, 9, tzinfo=UTC)


T0 = datetime(2026, 11, 9, tzinfo=UTC)
HOURS = [T0 + timedelta(hours=h) for h in range(8 * 24)]  # 9 Nov 00:00 .. 16 Nov 23:00 UTC
JUMP = datetime(2026, 11, 15, 23, tzinfo=UTC)  # 16 Nov 00:00 CET


def _hourly(item_id, price, qty=100):
    return [
        {
            "item_id": item_id,
            "hour": h,
            "min": price(h),
            "p25": price(h) + 10,
            "median": price(h) + 20,
            "p75": price(h) + 30,
            "quantity": qty(h) if callable(qty) else qty,
            "auctions": 5,
            "source": "api",
            "run_id": "r",
            "fetched_at": T0,
        }
        for h in HOURS
    ]


@pytest.fixture
def market(archive):
    """The shared archive plus hourly rows for a few items, economy totals and details."""
    store = Store(archive)
    rows = (
        # Rugged Leather: 1,000c, then 1,500c on the last CET day; quantity up there too.
        _hourly(8170, lambda h: 1500 if h >= JUMP else 1000, lambda h: 150 if h >= JUMP else 100)
        + _hourly(2447, lambda h: 50)  # Peacebloom (farmable): flat
        + _hourly(13468, lambda h: 2_000_000 + 20_000 * ((h - T0).days))  # Black Lotus (scarce)
    )
    store.upsert(TABLES["hourly"], to_arrow(TABLES["hourly"], rows))
    store.upsert(
        TABLES["economy"],
        to_arrow(
            TABLES["economy"],
            [
                {
                    "day": date(2026, 11, 9) + timedelta(days=k),
                    "kind": "daily",
                    "value": 1_000_000_000 + 100_000_000 * k,
                    "auctions": 1000 + 10 * k,
                    "units": 5000,
                    "scans": 24,
                    "source": "api",
                }
                for k in range(8)
            ],
        ),
    )
    t = datetime(2026, 11, 16, 8, tzinfo=UTC)
    base = {"name": "Rugged Leather", "quality": "COMMON", "item_class": "Trade Goods"}
    store.upsert(
        TABLES["items"],
        to_arrow(
            TABLES["items"],
            [
                {**base, "item_id": 8170, "level": 30, "fetched_at": t, "source": "api",
                 "subclass": "Leather", "vendor_price": 500},
                # A newer tooltip row (next day file) without details must not hide them.
                {**base, "item_id": 8170, "level": 30, "fetched_at": t + timedelta(days=1),
                 "source": "api"},
            ],
        ),
    )  # fmt: skip
    return archive


def test_overview_tiles_and_charts(market, config_dir):
    o = Bridge(market, now=NOW).overview()
    assert o["sub"] == "9 of 9 items"
    tiles = {t["label"]: t for t in o["tiles"]}
    assert tiles["Items tracked"]["value"] == "9"
    assert tiles["Items tracked"]["foot"] == "9 pass filters"
    # Weekly changes: Light Leather 0, Rugged Leather +50 %, Peacebloom 0, Black Lotus +7 %.
    assert tiles["Median price · 7 d"]["change"] == {"text": "▲ +3.5 %", "dir": "rise"}
    assert tiles["Median price · 7 d"]["foot"] == "farmable ± 0.0 %, scarce +7.0 %"
    assert tiles["Supply · 7 d"]["change"]["dir"] == "rise"
    assert tiles["Index divergence"]["value"].endswith(" pts")
    assert tiles["Gold listed · 7 d"]["extra"] and tiles["Gold listed · 7 d"]["coin"]["text"]
    assert o["index"]["sub"].startswith("9 Nov – 16 Nov 2026 · 8 d · 100 = ")
    assert len(o["index"]["x"]) == len(o["index"]["scarce"]) == len(o["index"]["divergence"])
    assert o["index"]["scarce"][-1] > 100 and o["index"]["farmable"][-1] > 100
    assert o["rhythm"]["hours"] == list(range(24)) and len(o["rhythm"]["labels"]) == 4
    groups = {r["name"]: r for r in o["rhythm"]["groups"]["rows"]}
    assert groups["Leather chain"]["items"] == "2 items"  # the two with hourly data
    assert o["rhythm"]["groups"]["sub"].endswith("lowest buyout, 07:00 vs 23:00")
    assert o["supply"]["sub"] == "9 Nov – 16 Nov 2026 · 8 d"
    assert len(o["supply"]["x"]) == len(HOURS)
    assert o["gold"]["sub"].endswith("whole market")
    assert o["gold"]["value"]["text"] == "170,000g"
    assert o["gold"]["change"] == {"text": "▲ +70 %", "dir": "rise"}


def test_overview_rhythm_needs_a_week(market, config_dir):
    # The archive covers 8 days: only the 24 h range is too short, so no ready date.
    b = Bridge(market, now=NOW)
    b.set_filters({"range": "24h"})
    gap = b.overview()["rhythm"]["gap"]
    assert gap["title"] == "Needs at least 7 days"
    assert gap["progress"] == "1 of 7 days"
    assert gap["ready"] == ""
    assert "widen the date range to 7 d or All" in gap["why"]


def test_overview_follows_filters_and_caches(market, config_dir):
    b = Bridge(market, now=NOW)
    first = b.overview()
    assert b.overview() is first  # same filters and archive: cached
    b.set_filters({"groups": ["Leather chain"]})
    leather = b.overview()
    assert leather["sub"] == "4 of 9 items"
    assert "No scarce goods" in leather["index"]["note"]


def test_overview_events_payload(market, config_dir):
    e = Bridge(market, now=NOW).overview_events()
    assert e["sub"].startswith("10 Nov – 16 Nov 2026")
    assert len(e["rows"]) <= vd.MAX_EVENTS


def test_what_changed_round_robin_weighted_by_sales():
    at = pd.Timestamp("2026-11-16 10:00", tz="UTC")
    shocks = PatternResult(
        events=events_frame(
            [
                {"item_id": 1, "at": at, "type": "supply_shock", "detail": "a", "magnitude": 9.0},
                {"item_id": 2, "at": at, "type": "supply_shock", "detail": "b", "magnitude": 0.8},
            ]
        )
    )
    buy = PatternResult(
        events=events_frame(
            [{"item_id": 3, "at": at, "type": "buyout", "detail": "c", "magnitude": 0.2}]
        )
    )
    out = vd.what_changed(
        [shocks, buy, None],
        {1: "Book page", 2: "Peacebloom", 3: "Thorium Bar"},
        {1: 0.1, 2: 12_000.0, 3: 50.0},
        date(2026, 11, 10),
        date(2026, 11, 16),
    )
    assert [r["name"] for r in out["rows"]] == ["Peacebloom", "Thorium Bar", "Book page"]
    assert out["rows"][0]["kind"] == "shock" and out["rows"][0]["type"] == "Supply shock"
    assert out["rows"][1]["when"] == "16 Nov, 11:00"
    assert out["sub"] == "10 Nov – 16 Nov 2026 · 3 events"


def test_item_list_sorts_and_shows_details(market, config_dir):
    b = Bridge(market, now=NOW)
    lst = b.item_list("change")
    assert lst["sub"] == "9 items · sorted by weekly change"
    top = lst["rows"][0]
    assert top["name"] == "Rugged Leather" and top["class"] == "Leather · Trade Goods"
    assert top["change"] == {"text": "▲ +50 %", "dir": "rise"}
    assert top["price"]["text"] == "14s 95c"
    assert [r["name"] for r in b.item_list()["rows"][:2]] == ["Light Leather", "Peacebloom"]
    assert b.item_list("bogus")["sort"] == "sales"


def test_item_detail(market, config_dir):
    d = Bridge(market, now=NOW).item_detail(8170)
    assert d["head"]["name"] == "Rugged Leather"
    assert d["head"]["sub"] == "Leather · Trade Goods · group Leather chain · 9 days of history"
    tiles = {t["label"]: t for t in d["tiles"]}
    assert tiles["Lowest buyout"]["coin"]["text"] == "14s 95c"
    assert tiles["Lowest buyout"]["foot"][0]["change"]["dir"] == "rise"
    assert tiles["Vendor price (floor)"]["coin"]["text"] == "5s"
    assert tiles["Vendor price (floor)"]["foot"] == ["buyout is 199.0 % above floor"]
    assert tiles["7-day median"]["foot"][0] == "lower quartile "
    c = d["chart"]
    assert c["sub"] == "9 Nov – 16 Nov 2026 · 8 d · 6 h buckets"
    assert len(c["x"]) == len(c["min"]) == len(c["quantity"]) == len(c["shock"]) == 32
    assert c["min"][0] == 1000 and c["p25"][0] == 1010
    assert c["vendor"] == {"value": 500, "label": "Vendor floor 5s"}
    p = d["profile"]
    assert len(p["values"]) == 24 and p["spread"].startswith("Spread ")
    assert d["events"]["sub"].startswith("9 Nov – 16 Nov 2026 · 8 d")
    leather = next(g for g in d["groups"] if g["name"] == "Leather chain")
    assert leather["member"] is True


def test_item_detail_without_vendor_price(market, config_dir):
    d = Bridge(market, now=NOW).item_detail(2447)
    vendor = next(t for t in d["tiles"] if t["label"] == "Vendor price (floor)")
    assert vendor["value"] == "–" and vendor["coin"] is None
    assert d["chart"]["vendor"] is None
    assert Bridge(market, now=NOW).item_detail(1)["missing"] is True


def test_short_range_uses_hour_buckets(market, config_dir):
    b = Bridge(market, now=NOW)
    b.set_filters({"range": "7d"})
    c = b.item_detail(8170)["chart"]
    assert c["sub"] == "10 Nov – 16 Nov 2026 · 7 d · 1 h buckets" and len(c["x"]) == 7 * 24


def test_add_to_group(market, config_dir):
    b = Bridge(market, now=NOW)
    b.add_to_group("Herbs", 13468)
    herbs = next(g for g in load_groups() if g.name == "Herbs")
    assert 13468 in herbs.item_ids
    d = b.item_detail(13468)
    assert next(g for g in d["groups"] if g["name"] == "Herbs")["member"] is True


def test_item_details_newest_non_null(market):
    assert item_details(market)[8170] == {"subclass": "Leather", "vendor_price": 500}
    assert 2447 not in item_details(market)


def test_item_details_old_files_without_columns(tmp_path):
    folder = tmp_path / "old"
    (folder / "items").mkdir(parents=True)
    pd.DataFrame({"item_id": [1], "name": ["X"], "fetched_at": [NOW()]}).to_parquet(
        folder / "items" / "2026-11-16.parquet"
    )
    assert item_details(folder) == {}
    assert item_details(tmp_path / "none") == {}


def test_memo_computes_once_for_concurrent_callers():
    memo = Memo()
    calls = []
    gate = threading.Event()

    def slow():
        calls.append(1)
        gate.wait(5)
        return "done"

    threads = [threading.Thread(target=memo.get, args=("k", slow)) for _ in range(4)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(5)
    assert calls == [1] and memo.get("k", slow) == "done"


def test_memo_forgets_failures():
    memo = Memo()

    def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        memo.get("k", boom)
    assert memo.get("k", lambda: 2) == 2


def test_view_methods_compute_without_the_lock(market, config_dir, monkeypatch):
    b = Bridge(market, now=NOW)
    free = []

    def try_lock():
        got = b.lock.acquire(blocking=False)
        free.append(got)
        if got:
            b.lock.release()

    def probe(inp):
        t = threading.Thread(target=try_lock)
        t.start()
        t.join(5)
        return {"sub": "probe"}

    monkeypatch.setattr(b, "_overview", probe)
    assert js_facade(b).overview() == {"sub": "probe"}
    assert free == [True]


def test_unlocked_methods_are_exposed():
    assert set(Bridge.UNLOCKED) <= set(Bridge.EXPOSED)


def test_item_list_keeps_the_pinned_item(market, config_dir):
    items = Bridge(market, now=NOW).items
    out = vd.item_list(items, pd.Series(dtype="float64"), {}, "name", 2, pin=8170)
    assert [r["name"] for r in out["rows"]] == [
        "Accurate Scope",
        "Black Lotus",
        "Rugged Leather",
    ]
    assert out["more"] == "first 2 shown"


def test_one_failing_event_job_keeps_the_others(market, config_dir, monkeypatch):
    from coppertrail.ui import bridge as bridge_mod

    real = bridge_mod.run_pattern

    def flaky(key, ctx):
        if key == "buyouts":
            raise RuntimeError("boom")
        return real(key, ctx)

    monkeypatch.setattr(bridge_mod, "run_pattern", flaky)
    e = Bridge(market, now=NOW).overview_events()
    assert e["failed"] == "Could not compute: buyouts"


def test_reload_clears_the_cache(market, config_dir):
    b = Bridge(market, now=NOW)
    first = b.overview()
    b._load()
    assert b.overview() is not first


def test_flat_rhythm_gets_one_label_per_series():
    md = pd.DataFrame(
        {"hour": range(24), "min_idx": 100.0, "p25_idx": 100.0, "quantity_idx": 100.0}
    )
    out = vd.rhythm_chart(
        PatternResult(charts={"market_day": md}), date(2026, 11, 10), date(2026, 11, 16), None
    )
    assert len(out["labels"]) == 2


def test_memo_drops_results_of_a_computation_that_outlived_a_clear():
    memo = Memo()

    def during_pull():
        memo.clear()  # a pull reloads while this computation runs
        return "old"

    assert memo.get("k", during_pull) == "old"
    assert memo.get("k", lambda: "new") == "new"


def test_memo_never_caches_inputs_from_an_older_generation():
    memo = Memo()
    gen = memo.generation
    memo.clear()
    assert memo.generation == gen + 1
    assert memo.get("k", lambda: "old", gen) == "old"
    assert memo.get("k", lambda: "new") == "new"


def test_pull_during_a_computation_does_not_keep_stale_results(market, config_dir, monkeypatch):
    b = Bridge(market, now=NOW)
    gen = b.state()["generation"]
    real = b._overview
    calls = []

    def racing(inp):
        calls.append(1)
        out = real(inp)
        if len(calls) == 1:
            b._load()  # the pull worker reloads before this result is stored
        return out

    monkeypatch.setattr(b, "_overview", racing)
    b.overview()
    assert not b.memo._futures  # neither the result nor its nested reads (week, economy)
    assert b.state()["generation"] != gen  # the page's view keys change after a load
    b.overview()
    assert len(calls) == 2  # recomputed after the reload


def test_item_detail_change_matches_the_item_list(market, config_dir):
    b = Bridge(market, now=NOW)
    row = next(r for r in b.item_list()["rows"] if r["id"] == 8170)
    tile = next(t for t in b.item_detail(8170)["tiles"] if t["label"] == "Lowest buyout")
    assert tile["foot"][0]["change"] == row["change"] == {"text": "▲ +50 %", "dir": "rise"}


def test_week_change_ignores_a_partial_base_day():
    # Item 2 has only 3 hourly rows on the base day: no "7 d" change, in list and header.
    base, last = date(2026, 11, 9), date(2026, 11, 16)
    daily = pd.DataFrame(
        {
            "item_id": [1, 1, 2, 2],
            "day": [base, last, base, last],
            "price": [100.0, 150.0, 10.0, 50.0],
            "p25": [100.0, 150.0, 10.0, 50.0],
            "qty": [1.0] * 4,
            "hours": [24, 24, 3, 24],
        }
    )
    changes = vd.week_change(daily)
    assert changes.to_dict() == {1: 0.5}
    empty = pd.DataFrame(columns=["p25", "quantity"])
    partial = Item(2, "X", "Trade Goods", "COMMON", 60, 1.0)
    tiles = vd.item_tiles(partial, None, empty, changes.get(2), None, base, last)
    assert tiles[0]["foot"] == ["latest price table"]
    full = Item(1, "Y", "Trade Goods", "COMMON", 160, 1.0)
    tiles = vd.item_tiles(full, None, empty, changes.get(1), None, base, last)
    assert tiles[0]["foot"][0]["change"] == {"text": "▲ +50 %", "dir": "rise"}
