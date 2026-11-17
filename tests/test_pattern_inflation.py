from datetime import date

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, make_ctx, noise, snapshot_frame

from coppertrail.patterns.inflation import classify, inflation

START = "2026-11-08 23:00"  # 00:00 CET on 9 Nov
DAYS = 8
N = DAYS * 24
ITEMS = [
    (13468, "Black Lotus", 60),
    (12363, "Arcane Crystal", 60),
    (2447, "Peacebloom", 5),
    (2318, "Light Leather", 10),
    (2320, "Coarse Thread", 5),
    (999, "Some Sword", 30),
]


def _series(item_id, daily):
    day = np.arange(N) // 24
    return hourly_frame(item_id, START, {"min": 1000 * daily**day * noise(N, item_id, 0.01)})


def _economy():
    days = pd.date_range("2026-11-09", periods=DAYS).date
    return pd.DataFrame(
        {
            "day": days,
            "kind": "daily",
            "value": [10_000_000 * (i + 1) for i in range(DAYS)],
            "value_low": np.nan,
            "auctions": 1000,
            "units": 5000,
            "scans": 100,
            "source": "api",
        }
    )


def _ctx(drifts):
    return make_ctx(
        hourly=pd.concat([_series(i, drifts[i]) for i, _, _ in ITEMS], ignore_index=True),
        items=items_frame(ITEMS),
        snapshot=snapshot_frame({i: 100.0 for i, _, _ in ITEMS}),
        economy=_economy(),
    )


def test_classify_uses_starter_groups():
    g = classify(items_frame(ITEMS))
    assert g[13468] == "scarce" and g[12363] == "scarce"  # Black Lotus is a herb too
    assert g[2447] == "farmable" and g[2318] == "farmable"
    assert g[2320] == "vendor"
    assert 999 not in g.index


def test_planted_divergence():
    drifts = {13468: 1.04, 12363: 1.04, 2447: 0.96, 2318: 0.96, 2320: 1.0, 999: 1.5}
    res = inflation(_ctx(drifts))
    idx = res.charts["index"]
    last = idx[idx["day"] == idx["day"].max()].set_index("group")["index"]
    assert 125 < last["scarce"] < 140  # 1.04^7 = 1.316
    assert 70 < last["farmable"] < 80  # 0.96^7 = 0.751
    assert 97 < last["vendor"] < 103
    first = idx[idx["day"] == date(2026, 11, 9)]["index"]
    assert np.allclose(first, 100)
    div = res.charts["divergence"]
    assert div["divergence"].iloc[-1] > 50 and abs(div["divergence"].iloc[0]) < 1e-9
    assert res.items_checked == 5  # the sword is in no group
    assert res.items_hit == 4
    econ = res.charts["economy"]
    assert econ["gold_listed"].iloc[0] == 1000 and econ["gold_index"].iloc[-1] == 800
    assert list(res.ranked.columns[:2]) == ["item_id", "name"]


def test_flat_noise_shows_no_inflation():
    res = inflation(_ctx(dict.fromkeys([i for i, _, _ in ITEMS], 1.0)))
    assert res.items_hit == 0
    assert res.charts["index"]["index"].between(95, 105).all()
