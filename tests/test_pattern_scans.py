"""Patterns 3 (mispricings) and 5 (buyouts) on synthetic hourly snapshot series."""

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, latest_frame, make_ctx, noise

from coppertrail.patterns.base import EVENT_COLS
from coppertrail.patterns.buyouts import buyouts
from coppertrail.patterns.mispricings import mispricings

START = "2026-11-15 20:00"
N = 144  # 6 days of hourly snapshots


def _ctx(frames, ids):
    return make_ctx(
        hourly=pd.concat(frames, ignore_index=True),
        items=items_frame([(i, f"Item {i}", 30) for i in ids]),
        latest=latest_frame({i: 50.0 for i in ids}),
    )


def _flat(item_id, seed=None, jitter=False):
    m = 1000 * noise(N, seed or item_id, 0.02)
    q = 200 * noise(N, (seed or item_id) + 100, 0.05)
    # Blizzard's snapshot time wanders by up to a minute either way.
    js = np.random.default_rng(item_id).uniform(-60, 60, N) if jitter else None
    return hourly_frame(item_id, START, {"min": m, "p25": m * 1.1, "quantity": q}, js)


def test_planted_mispricing_and_its_correction():
    df = _flat(1)
    # Snapshots 60-62 (3 h) list at 40 % of the normal p25; p25 itself unchanged.
    df.loc[60:62, "min"] = 450.0
    df.loc[110, "min"] = 500.0  # and a second, single-scan one
    res = mispricings(_ctx([df, _flat(2)], [1, 2]))
    assert res.items_hit == 1 and res.items_checked == 2
    ev = res.events
    assert list(ev.columns) == EVENT_COLS
    assert len(ev) == 2 and set(ev["type"]) == {"mispricing"}
    assert ev["at"].iloc[0] == df["observed_at"].iloc[60]
    assert -0.65 < ev["magnitude"].iloc[0] < -0.55
    detail = res.charts["events"].iloc[0]
    assert detail["scans"] == 3 and detail["minutes_to_correct"] == 180
    top = res.ranked.iloc[0]
    assert top["item_id"] == 1 and top["events"] == 2 and top["corrected_share"] == 1.0
    assert res.charts["by_hour"]["events"].sum() == 2


def test_one_mispricing_is_not_a_hit():
    df = _flat(1)
    df.loc[60, "min"] = 450.0
    res = mispricings(_ctx([df], [1]))
    assert len(res.events) == 1 and res.items_hit == 0


def test_mispricing_not_corrected_by_end():
    df = _flat(1)
    df.loc[N - 2 :, "min"] = 300.0
    res = mispricings(_ctx([df], [1]))
    assert np.isnan(res.charts["events"]["minutes_to_correct"].iloc[0])
    assert "not corrected" in res.events["detail"].iloc[0]


def test_flat_noise_has_no_mispricings_or_buyouts():
    ctx = _ctx([_flat(i) for i in range(3, 8)], list(range(3, 8)))
    for job in (mispricings, buyouts):
        res = job(ctx)
        assert res.items_hit == 0 and res.events.empty and res.ranked.empty
        assert res.items_checked == 5


def test_planted_buyout_and_reset():
    df = _flat(1)
    # At snapshot 80 someone buys 70 % of the market; min +50 %, normal 2 h later.
    df.loc[80:81, "quantity"] = 60.0
    df.loc[80:81, "min"] = 1500.0
    df.loc[120, "quantity"] = 60.0  # a second one, reset after 1 h
    df.loc[120, "min"] = 1500.0
    res = buyouts(_ctx([df, _flat(2)], [1, 2]))
    assert res.items_hit == 1
    ev = res.events
    assert len(ev) == 2 and set(ev["type"]) == {"buyout"}
    assert ev["at"].iloc[0] == df["observed_at"].iloc[80]
    assert 0.4 < ev["magnitude"].iloc[0] < 0.6
    d = res.charts["events"].iloc[0]
    assert d["quantity_drop"] < -0.6 and d["minutes_to_reset"] == 120
    assert res.ranked.iloc[0]["buyouts"] == 2


def test_buyout_needs_both_signals():
    df = _flat(1)
    df.loc[80:, "quantity"] = 60.0  # quantity drop alone
    df2 = _flat(2)
    df2.loc[80:, "min"] = 1500.0  # price jump alone
    res = buyouts(_ctx([df, df2], [1, 2]))
    assert res.items_hit == 0


def test_staged_buyout_counts_once():
    df = _flat(1)
    df.loc[80:91, ["quantity", "min"]] = [100.0, 1300.0]  # first step
    df.loc[81:91, ["quantity", "min"]] = [40.0, 1700.0]  # second step, next snapshot
    res = buyouts(_ctx([df], [1]))
    assert len(res.events) == 1


def test_correction_after_a_missed_snapshot_is_unknown():
    df = _flat(1)
    df.loc[60, "min"] = 450.0
    df = df.drop(index=[61])  # one missed snapshot: the next one is 2 h later
    res = mispricings(_ctx([df], [1]))
    assert np.isnan(res.charts["events"]["minutes_to_correct"].iloc[0])


def test_snapshot_timing_jitter_keeps_events():
    df = _flat(1, jitter=True)
    df.loc[60:62, "min"] = 450.0
    df.loc[80:81, ["quantity", "min"]] = [60.0, 1500.0]
    ctx = _ctx([df], [1])
    mis = mispricings(ctx).charts["events"]
    assert len(mis) == 1 and mis["scans"].iloc[0] == 3
    assert np.isfinite(mis["minutes_to_correct"].iloc[0])
    buy = buyouts(ctx).charts["events"]
    assert len(buy) == 1 and np.isfinite(buy["minutes_to_reset"].iloc[0])
