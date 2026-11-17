import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, make_ctx, noise, snapshot_frame

from coppertrail.patterns.base import EVENT_COLS
from coppertrail.patterns.supply import supply_shocks

START = "2026-11-09 00:00"
N = 8 * 24


def _ctx(frames, ids):
    return make_ctx(
        hourly=pd.concat(frames, ignore_index=True),
        items=items_frame([(i, f"Item {i}", 30) for i in ids]),
        snapshot=snapshot_frame({i: 80.0 for i in ids}),
    )


def _flat(item_id):
    return hourly_frame(
        item_id,
        START,
        {"min": 1000 * noise(N, item_id, 0.02), "quantity": 100 * noise(N, item_id + 50, 0.05)},
    )


def test_planted_shock_with_lagged_price_drop():
    df = _flat(1)
    df.loc[100:105, "quantity"] = 260.0  # +160 % for 6 h
    df.loc[103:108, "min"] = 800.0  # min -20 % for 6 h, 3 h after the shock
    res = supply_shocks(_ctx([df, _flat(2)], [1, 2]))
    assert res.items_checked == 2 and res.items_hit == 1
    ev = res.events
    assert list(ev.columns) == EVENT_COLS
    assert len(ev) == 1 and ev["type"].iloc[0] == "supply_shock"
    assert ev["at"].iloc[0] == df["hour"].iloc[100]
    assert 1.4 < ev["magnitude"].iloc[0] < 1.8
    d = res.charts["events"].iloc[0]
    assert d["hours"] == 6
    assert -0.25 < d["price_change"] < -0.15 and 3 <= d["lag_hours"] <= 10
    top = res.ranked.iloc[0]
    assert top["item_id"] == 1 and top["price_followed_share"] == 1.0
    assert top["xcorr"] < 0 and top["xcorr_lag_hours"] == 3
    resp = res.charts["response"]
    assert set(resp["lag"]) == set(range(13))


def test_flat_noise_has_no_shocks():
    res = supply_shocks(_ctx([_flat(i) for i in range(3, 8)], list(range(3, 8))))
    assert res.items_hit == 0 and res.events.empty and res.ranked.empty
