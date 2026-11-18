from datetime import date

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, latest_frame, make_ctx, noise

from coppertrail.patterns.progression import band_of, progression_wave, turning_point

START = "2026-11-08 23:00"  # 00:00 CET on 9 Nov
DAYS = 9
N = DAYS * 24


def _wave(item_id):
    # Supply +30 %/day for the first 4 days, then flat; price falls along with it.
    day = np.arange(N) // 24
    growth = 1.3 ** np.minimum(day, 4)
    return hourly_frame(
        item_id,
        START,
        {
            "min": 1000 / growth * noise(N, item_id),
            "quantity": 100 * growth * noise(N, item_id + 9),
        },
    )


def _flat(item_id):
    return hourly_frame(
        item_id,
        START,
        {"min": 1000 * noise(N, item_id), "quantity": 100 * noise(N, item_id + 9, 0.05)},
    )


def _ctx(frames, levels):
    return make_ctx(
        hourly=pd.concat(frames, ignore_index=True),
        items=items_frame([(i, f"Item {i}", lv) for i, lv in levels.items()]),
        latest=latest_frame({i: 10.0 for i in levels}),
    )


def test_planted_wave_finds_turning_point_in_band_60():
    ids60, ids20 = [1, 2, 3], [4, 5, 6]
    ctx = _ctx(
        [_wave(i) for i in ids60] + [_flat(i) for i in ids20],
        {1: 60, 2: 60, 3: 60, 4: 22, 5: 25, 6: 28},
    )
    res = progression_wave(ctx)
    assert res.items_checked == 6 and res.items_hit == 3
    tp = res.charts["turning_points"].set_index("band")
    assert tp.loc["60", "turning_day"] in (date(2026, 11, 14), date(2026, 11, 15))
    assert tp.loc["60", "supply_change"] > 1.5 and tp.loc["60", "price_change"] < -0.5
    assert tp.loc["20-29", "turning_day"] is None or pd.isna(tp.loc["20-29", "turning_day"])
    assert set(res.ranked["item_id"].head(3)) == set(ids60)
    assert list(res.ranked.columns[:2]) == ["item_id", "name"]
    assert set(res.charts["bands"]["band"]) == {"60", "20-29"}


def test_flat_noise_has_no_turning_point():
    res = progression_wave(_ctx([_flat(i) for i in range(1, 6)], dict.fromkeys(range(1, 6), 40)))
    assert res.items_hit == 0


def test_helpers():
    assert band_of(60) == "60" and band_of(1) == "1-9" and band_of(55) == "50-59"
    assert band_of(float("nan")) is None
    s = pd.Series([100, 130, 169, 220, 221, 222, 223], index=range(7), dtype=float)
    peak, peak_day, turn = turning_point(s)
    assert peak > 0.25 and turn == 5
    assert turning_point(s.iloc[:6])[2] is None  # one flat day at the end is not enough
