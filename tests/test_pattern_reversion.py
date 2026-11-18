from datetime import date

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, latest_frame, make_ctx, noise

import coppertrail.patterns.reversion  # noqa: F401  (registers the job)
from coppertrail.patterns.base import run
from coppertrail.patterns.reversion import RANKED_COLS, mean_reversion

START = "2026-10-31 23:00"  # 00:00 CET on 1 Nov
DAYS = 30
N = DAYS * 24
DIP, TREND, FLAT = 1001, 1002, 1003
ITEMS = [(DIP, "Dip Herb", 30), (TREND, "Falling Ore", 30), (FLAT, "Flat Cloth", 30)]


def _hourly(item_id, daily):
    """Hourly min from a per-day price level, with 2 % hourly noise."""
    day = np.arange(N) // 24
    return hourly_frame(item_id, START, {"min": daily[day] * noise(N, item_id, 0.02)})


def _ctx(series, **kw):
    hourly = pd.concat([_hourly(i, d) for i, d in series.items()], ignore_index=True)
    return make_ctx(
        hourly=hourly,
        items=items_frame(ITEMS),
        latest=latest_frame(dict.fromkeys(series, 50.0)),
        **kw,
    )


def _dip():
    d = np.full(DAYS, 1000.0)
    d[np.arange(6, DAYS, 6)] = 750  # 1-day 25 % dips on days 6, 12, 18, 24
    return d


def _trend():
    day = np.arange(DAYS)
    return 1000 * 0.97**day * 0.8 ** (day // 6)  # -3 %/day plus a 20 % step every 6 days


def test_planted_dips_recover():
    res = mean_reversion(_ctx({DIP: _dip(), TREND: _trend(), FLAT: np.full(DAYS, 1000.0)}))
    r = res.ranked.set_index("item_id")
    assert list(res.ranked.columns) == ["item_id", "name", *RANKED_COLS]
    assert res.ranked["item_id"].iloc[0] == DIP
    dip = r.loc[DIP]
    assert dip["signals"] == 4 and dip["recovered"] == 4
    assert dip["hit_rate"] == 1.0
    assert dip["base_rate"] < 0.2 and dip["edge"] > 0.8
    assert dip["median_days"] == 1.0
    assert 0.2 < dip["median_return"] < 0.3  # 1000 * 0.95 / 750 - 1 = 0.267
    trend = r.loc[TREND]
    # The steps keep the price below the threshold for long runs, which count once each.
    assert trend["signals"] >= 1 and trend["recovered"] == 0 and trend["hit_rate"] == 0
    assert trend["median_return"] < 0 and trend["base_rate"] == 0
    assert FLAT not in r.index  # no signal, not listed
    assert res.items_hit == 1 and res.items_checked == 3
    sig = res.charts["signals"]
    assert set(sig.loc[sig["item_id"] == DIP, "day"]) == {
        date(2026, 11, d) for d in (7, 13, 19, 25)
    }
    ser = res.charts["series"]
    assert {"item_id", "day", "price", "mean7", "threshold"} <= set(ser.columns)
    assert len(ser) == 3 * DAYS
    assert "first day of a run" in res.note


def test_flat_noise_has_no_signals():
    flat = {i: np.full(DAYS, 1000.0) for i, _, _ in ITEMS}
    res = mean_reversion(_ctx(flat))
    assert res.items_hit == 0 and res.ranked.empty and res.charts["signals"].empty
    assert res.items_checked == 3


def test_pending_signal_at_the_end_is_left_out():
    d = np.full(DAYS, 1000.0)
    d[DAYS - 2] = 700  # horizon runs past the data
    res = mean_reversion(_ctx({DIP: d}))
    r = res.ranked.set_index("item_id").loc[DIP]
    assert r["signals"] == 0 and r["pending"] == 1
    assert "1 pending" in res.note


def test_empty_input():
    res = mean_reversion(make_ctx())
    assert res.ranked.empty and list(res.ranked.columns[:2]) == ["item_id", "name"]
    assert res.charts["signals"].empty and res.charts["series"].empty


def test_gate_needs_21_days():
    ctx = _ctx({DIP: _dip()}, start=date(2026, 11, 1), end=date(2026, 11, 8))
    res = run("mean_reversion", ctx)
    assert res.needs_days == 13 and res.ready_on == date(2026, 11, 21)
