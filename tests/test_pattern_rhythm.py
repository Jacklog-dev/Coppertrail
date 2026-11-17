import numpy as np
import pandas as pd
from pattern_fixtures import (
    hourly_frame,
    items_frame,
    local_hours,
    make_ctx,
    noise,
    snapshot_frame,
)

from coppertrail.patterns.rhythm import confidence, daily_rhythm

START = "2026-11-08 23:00"  # 00:00 CET on 9 Nov
N = 10 * 24


def _ctx(frames, ids):
    return make_ctx(
        hourly=pd.concat(frames, ignore_index=True),
        items=items_frame([(i, f"Item {i}", 30) for i in ids]),
        snapshot=snapshot_frame({i: 100.0 for i in ids}),
    )


def _rhythm_item(item_id: int) -> pd.DataFrame:
    hod = local_hours(START, N)
    # Cheap in the evening, dear in the morning: +20 % from 22:00 to 07:00.
    shape = np.where((hod >= 20) | (hod <= 1), 0.9, np.where((hod >= 6) & (hod <= 10), 1.1, 1.0))
    price = 1000 * shape * noise(N, item_id, 0.01)
    return hourly_frame(item_id, START, {"min": price, "quantity": 100 * noise(N, 1)})


def _flat_item(item_id: int, drift: float = 0.0) -> pd.DataFrame:
    price = 1000 * noise(N, item_id, 0.02) * (1 + drift) ** np.arange(N)
    return hourly_frame(item_id, START, {"min": price})


def test_planted_rhythm_wins_most_nights():
    res = daily_rhythm(_ctx([_rhythm_item(1), _flat_item(2)], [1, 2]))
    top = res.ranked.iloc[0]
    assert top["item_id"] == 1
    assert top["nights"] >= 8 and top["wins"] == top["nights"]
    assert 0.1 < top["median_result"] < 0.25  # 1.1/0.9 * 0.95 - 1 = +16 %
    assert top["cheapest_hour"] in (20, 21, 22, 23, 0, 1)
    assert top["dearest_hour"] in (6, 7, 8, 9, 10)
    assert top["confidence"] == "medium"
    assert res.items_checked == 2 and res.items_hit == 1
    assert list(res.ranked.columns[:2]) == ["item_id", "name"]
    assert {"nights", "typical_day", "market_day"} <= set(res.charts)
    assert len(res.charts["market_day"]) == 24


def test_flat_noise_does_not_fire():
    res = daily_rhythm(_ctx([_flat_item(i) for i in (3, 4, 5)], [3, 4, 5]))
    assert res.items_hit == 0
    assert (res.ranked["median_result"] < 0).all()  # the 5 % cut eats a flat night


def test_trend_is_removed_before_testing():
    # +1.5 %/h drift: raw overnight result is about +8 %, detrended it is the cut.
    res = daily_rhythm(_ctx([_flat_item(6, drift=0.015)], [6]))
    nights = res.charts["nights"]
    assert nights["raw_result"].median() > 0.05
    assert abs(nights["result"].median() + 0.05) < 0.03
    assert res.items_hit == 0


def test_confidence_labels():
    assert confidence(30, 0.8) == "high"
    assert confidence(8, 0.8) == "medium"
    assert confidence(5, 1.0) == "low"
    assert confidence(30, 0.5) == "low"
