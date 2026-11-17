from datetime import date

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, make_ctx, snapshot_frame

import coppertrail.patterns.correlations  # noqa: F401  (registers the job)
from coppertrail.patterns.base import run
from coppertrail.patterns.correlations import correlations

START = "2026-10-31 23:00"  # 00:00 CET on 1 Nov
DAYS = 30
IDS = [10, 20, 30, 40, 50, 60, 70, 80]


def _shocks(seed, scale=0.05):
    return np.random.default_rng(seed).normal(0, scale, DAYS)


def _hourly(item_id, shocks):
    """Daily level = 1000 * exp(cumsum(shocks)), held for 24 hours, tiny hourly noise."""
    level = 1000 * np.exp(np.cumsum(shocks))
    hourly = np.repeat(level, 24) * (1 + np.random.default_rng(item_id).normal(0, 0.001, DAYS * 24))
    return hourly_frame(item_id, START, {"min": hourly})


def _ctx(shocks: dict[int, np.ndarray], start=date(2026, 11, 1), end=date(2026, 11, 30)):
    ids = list(shocks)
    return make_ctx(
        hourly=pd.concat([_hourly(i, s) for i, s in shocks.items()], ignore_index=True),
        items=items_frame([(i, f"Item {i}", 30) for i in ids]),
        snapshot=snapshot_frame({i: 10.0 * (k + 1) for k, i in enumerate(ids)}),
        start=start,
        end=end,
    )


def _independent():
    return {i: _shocks(i) for i in IDS}


def test_planted_lagged_and_same_day_pairs():
    s = _independent()
    s[50] = np.concatenate([_shocks(99, 0.05)[:2], s[20][:-2]])  # 50 follows 20 by 2 days
    s[70] = s[30] + _shocks(77, 0.01)  # 70 moves with 30 on the same day
    res = correlations(_ctx(s))
    r = res.ranked
    assert list(r.columns[:2]) == ["item_id", "name"]
    lagged = r[(r["item_id"] == 20) & (r["partner_id"] == 50)].iloc[0]
    assert lagged["lag_days"] == 2 and lagged["corr"] > 0.8 and lagged["hit"]
    assert lagged["partner_name"] == "Item 50" and lagged["n_days"] >= 14
    same = r[(r["item_id"] == 30) & (r["partner_id"] == 70)].iloc[0]
    assert same["lag_days"] == 0 and same["corr"] > 0.8
    assert set(r.loc[r["hit"], "item_id"]) | set(r.loc[r["hit"], "partner_id"]) == {20, 50, 30, 70}
    assert res.items_checked == 8 and res.items_hit == 4
    assert (r["lag_days"] >= 0).all() and r["corr"].abs().is_monotonic_decreasing
    assert len(r) == 28  # all pairs, fewer than TOP
    lags = res.charts["lags"]
    pl = lags[(lags["item_id"] == 20) & (lags["partner_id"] == 50)].set_index("lag")["corr"]
    assert list(pl.index) == list(range(-3, 4)) and pl.abs().idxmax() == 2
    ser = res.charts["series"]
    assert list(ser.columns) == ["item_id", "day", "price", "resid"]
    assert set(ser["item_id"]) == set(IDS)
    assert "28 pairs tested" in res.note and "by chance" in res.note


def test_common_market_trend_makes_no_pairs():
    market = _shocks(500, 0.08) + 0.02  # shared shocks and drift, larger than own noise
    res = correlations(_ctx({i: market + _shocks(i, 0.03) for i in IDS}))
    assert res.items_hit == 0
    assert not res.ranked["hit"].any()


def test_independent_noise_has_no_hits():
    res = correlations(_ctx(_independent()))
    assert res.items_checked == 8 and res.items_hit == 0


def test_sparse_items_are_skipped_and_counted():
    ctx = _ctx(_independent())
    h = ctx.hourly
    days = h["hour"].dt.tz_convert("Europe/Berlin").dt.day
    ctx.__dict__["hourly"] = h[~((h["item_id"] == 80) & (days <= 10))]
    res = correlations(ctx)
    assert res.items_checked == 7 and "1 items priced on fewer" in res.note


def test_empty_input():
    res = correlations(make_ctx())
    assert res.ranked.empty and list(res.ranked.columns[:2]) == ["item_id", "name"]
    assert res.items_checked == 0 and set(res.charts) == {"series", "lags"}
    one = correlations(_ctx({10: _shocks(10)}))
    assert one.ranked.empty and one.items_checked == 1


def test_gate_needs_21_days():
    res = run("correlations", _ctx(_independent(), date(2026, 11, 1), date(2026, 11, 8)))
    assert res.needs_days == 13 and res.ready_on == date(2026, 11, 21)
