from datetime import date

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, latest_frame, make_ctx, noise

import coppertrail.patterns.builds  # noqa: F401  (registers the job)
from coppertrail.patterns.base import run
from coppertrail.patterns.builds import build_effects

START = "2026-11-09 00:00"
DAYS = 8
N = DAYS * 24
BUILD_AT = pd.Timestamp("2026-11-13 14:00", tz="UTC")  # hour 110 of the data
ITEMS = [
    (2318, "Light Leather", 10),
    (4234, "Heavy Leather", 30),
    (2589, "Linen Cloth", 5),
    (2770, "Copper Ore", 5),
    (999, "Some Sword", 30),
]
JUMPERS = {2318, 4234}


def _builds(times):
    return pd.DataFrame(
        {
            "build_id": range(1, len(times) + 1),
            "version": [f"1.0.{i}" for i in range(len(times))],
            "stage": "live",
            "title": [f"WoW Forever 1.0.{i} (build {i})" for i in range(len(times))],
            "published_at": pd.to_datetime(times, utc=True),
            "url": [f"https://example.invalid/{i}" for i in range(len(times))],
        }
    )


def _hourly(price_fn, qty_fn=None):
    hours = pd.date_range(START, periods=N, freq="h", tz="UTC")
    frames = []
    for i, _, _ in ITEMS:
        vals = {"min": price_fn(i, hours) * noise(N, i, 0.02)}
        if qty_fn is not None:
            vals["quantity"] = qty_fn(i, hours) * noise(N, i + 1, 0.02)
        frames.append(hourly_frame(i, START, vals))
    return pd.concat(frames, ignore_index=True)


def _ctx(h, builds):
    return make_ctx(
        hourly=h,
        items=items_frame(ITEMS),
        latest=latest_frame({i: 50.0 for i, _, _ in ITEMS}),
        builds=builds,
        start=date(2026, 11, 9),
        end=date(2026, 11, 16),
    )


def _jump(i, hours):
    return np.where((i in JUMPERS) & (hours >= BUILD_AT), 1300.0, 1000.0)


def test_planted_jump_is_found_and_unusable_build_counted():
    res = build_effects(_ctx(_hourly(_jump), _builds([BUILD_AT, "2026-11-25 10:00"])))
    r = res.ranked
    assert list(r.columns[:2]) == ["item_id", "name"]
    assert set(r["item_id"].iloc[:2]) == JUMPERS
    top = r.iloc[0]
    assert 0.25 < top["excess_price"] < 0.35 and abs(top["placebo_price"]) < 0.02
    assert top["build"] == "1.0.0" and top["builds_tested"] == 1
    assert res.items_hit == 2 and res.items_checked == 5
    b = res.charts["builds"]
    assert b["usable"].tolist() == [True, False] and b["items"].tolist() == [5, 0]
    assert "Only 1 of 2 builds" in res.note and "anecdotes" in res.note
    g = res.charts["groups"].set_index("group")
    assert g.loc["Leather chain", "items"] == 2
    assert 0.25 < g.loc["Leather chain", "median_excess_price"] < 0.35
    assert abs(g.loc["All", "median_excess_price"]) < 0.05
    w = res.charts["window"]
    lw = w[w["item_id"] == 2318]
    assert lw["offset_h"].min() == -72 and lw["offset_h"].max() == 72
    assert lw.loc[lw["offset_h"] < 0, "price_idx"].between(90, 110).all()
    assert lw.loc[lw["offset_h"] >= 0, "price_idx"].between(117, 143).all()


def test_market_downtrend_is_absorbed_by_placebo():
    def down(i, hours):
        return 1000.0 * 0.97 ** ((hours - hours[0]) / pd.Timedelta(days=1))

    res = build_effects(_ctx(_hourly(down, down), _builds([BUILD_AT])))
    r = res.ranked
    assert len(r) == 5 and res.items_hit == 0
    assert r["price_change"].between(-0.05, -0.01).all()  # the raw change shows the drift
    assert r["excess_price"].abs().max() < 0.03
    assert r["excess_supply"].abs().max() < 0.03
    assert "Only 1 of 1 build" in res.note


def test_placebo_needs_two_anchors():
    # Build two days into the data: only anchors at +48 h and later remain, but the
    # data ends at day 4, so there is one anchor at most.
    h = _hourly(_jump)
    h = h[h["hour"] < pd.Timestamp("2026-11-13 00:00", tz="UTC")]
    res = build_effects(_ctx(h, _builds(["2026-11-10 12:00"])))
    assert res.ranked["placebo_price"].isna().all()
    assert res.ranked["excess_price"].isna().all() and res.items_hit == 0
    assert "lack a placebo" in res.note


def test_empty_builds_and_empty_hourly():
    res = build_effects(_ctx(_hourly(_jump), None))
    assert res.ranked.empty and list(res.ranked.columns[:2]) == ["item_id", "name"]
    assert res.charts["builds"].empty and res.charts["groups"].empty
    assert "No builds in the range" in res.note
    res = build_effects(_ctx(None, _builds([BUILD_AT])))
    assert res.ranked.empty and res.items_checked == 0
    assert res.charts["builds"]["usable"].tolist() == [False]
    assert "Only 0 of 1 build" in res.note


def test_run_gate_and_registration():
    ctx = _ctx(_hourly(_jump), _builds([BUILD_AT]))
    res = run("build_effects", ctx)
    assert res.ready and res.items_hit == 2 and "anecdotes" in res.method
    ctx = _ctx(None, None)
    ctx.__dict__["span"] = (None, None)  # empty archive
    res = run("build_effects", ctx)
    assert res.needs_days == 1 and res.ready_on == date(2026, 11, 17)


def test_spike_hours_and_noisy_items_are_no_hits():
    # A few fantasy-priced hours after the build (x50) must not move a median window,
    # and an item swinging 30 % from day to day must not pass on its own noise.
    spike_at = BUILD_AT + pd.Timedelta(hours=3)

    def price(i, hours):
        p = np.full(len(hours), 1000.0)
        if i == 2318:
            p[(hours >= spike_at) & (hours < spike_at + pd.Timedelta(hours=3))] = 50_000.0
        if i == 2770:
            day = ((hours - hours[0]) // pd.Timedelta(days=1)).to_numpy()
            level = np.random.default_rng(7).lognormal(0, 0.3, DAYS)
            p = p * level[day]
        return p

    res = build_effects(_ctx(_hourly(price), _builds([BUILD_AT])))
    r = res.ranked.set_index("item_id")
    assert abs(r.loc[2318, "price_change"]) < 0.05
    assert r.loc[2770, "placebo_spread"] > 0.1
    assert res.items_hit == 0
