"""Patterns 3 (mispricings) and 5 (buyouts) on synthetic scan series."""

import numpy as np
import pandas as pd
from pattern_fixtures import items_frame, make_ctx, noise, scans_frame, snapshot_frame

from coppertrail.patterns.base import EVENT_COLS
from coppertrail.patterns.buyouts import buyouts
from coppertrail.patterns.mispricings import mispricings

START = "2026-11-15 20:00"
N = 144  # 24 h at 10 min


def _ctx(frames, ids):
    return make_ctx(
        scans=pd.concat(frames, ignore_index=True),
        items=items_frame([(i, f"Item {i}", 30) for i in ids]),
        snapshot=snapshot_frame({i: 50.0 for i in ids}),
    )


def _flat(item_id, seed=None):
    m = 1000 * noise(N, seed or item_id, 0.02)
    q = 200 * noise(N, (seed or item_id) + 100, 0.05)
    return scans_frame(item_id, START, 10, {"min": m, "p25": m * 1.1, "quantity": q})


def test_planted_mispricing_and_its_correction():
    df = _flat(1)
    # Scans 60-62 (30 min) list at 40 % of the normal p25; p25 itself unchanged.
    df.loc[60:62, "min"] = 450.0
    res = mispricings(_ctx([df, _flat(2)], [1, 2]))
    assert res.items_hit == 1 and res.items_checked == 2
    ev = res.events
    assert list(ev.columns) == EVENT_COLS
    assert len(ev) == 1 and ev["type"].iloc[0] == "mispricing"
    assert ev["at"].iloc[0] == df["observed_at"].iloc[60]
    assert -0.65 < ev["magnitude"].iloc[0] < -0.55
    detail = res.charts["events"].iloc[0]
    assert detail["scans"] == 3 and detail["minutes_to_correct"] == 30
    top = res.ranked.iloc[0]
    assert top["item_id"] == 1 and top["events"] == 1 and top["corrected_share"] == 1.0
    assert res.charts["by_hour"]["events"].sum() == 1


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
    # At scan 80 someone buys 70 % of the market; min +50 %, back to normal 2 h later.
    df.loc[80:91, "quantity"] = 60.0
    df.loc[80:91, "min"] = 1500.0
    res = buyouts(_ctx([df, _flat(2)], [1, 2]))
    assert res.items_hit == 1
    ev = res.events
    assert len(ev) == 1 and ev["type"].iloc[0] == "buyout"
    assert ev["at"].iloc[0] == df["observed_at"].iloc[80]
    assert 0.4 < ev["magnitude"].iloc[0] < 0.6
    d = res.charts["events"].iloc[0]
    assert d["quantity_drop"] < -0.6 and d["minutes_to_reset"] == 120
    assert res.ranked.iloc[0]["buyouts"] == 1


def test_buyout_needs_both_signals():
    df = _flat(1)
    df.loc[80:, "quantity"] = 60.0  # quantity drop alone
    df2 = _flat(2)
    df2.loc[80:, "min"] = 1500.0  # price jump alone
    res = buyouts(_ctx([df, df2], [1, 2]))
    assert res.items_hit == 0
