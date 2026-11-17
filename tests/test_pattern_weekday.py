from datetime import date, timedelta

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, make_ctx, noise, snapshot_frame

import coppertrail.patterns.weekday  # noqa: F401  (registers the job)
from coppertrail.patterns.base import run
from coppertrail.patterns.weekday import weekday_reset

START = "2026-11-08 23:00"  # 00:00 CET on Monday 9 Nov
N = 35 * 24  # five weeks
HOURS = pd.date_range(START, periods=N, freq="h", tz="UTC")


def _saturday_item(item_id):
    local = HOURS.tz_convert("Europe/Berlin")
    bump = np.where(local.day_of_week == 5, 1.15, 1.0)
    trend = 0.995 ** (np.arange(N) / 24)  # mild downtrend, removed by the rolling mean
    return hourly_frame(item_id, START, {"min": 1000 * bump * trend * noise(N, item_id, 0.01)})


def _reset_item(item_id):
    since = (HOURS - pd.Timedelta(hours=4)).day_of_week == 2  # 24 h from Wed 04:00 UTC
    bump = np.where(since, 1.2, 1.0)
    return hourly_frame(item_id, START, {"min": 1000 * bump * noise(N, item_id, 0.01)})


def _flat_item(item_id):
    return hourly_frame(
        item_id, START, {"min": 1000 * noise(N, item_id), "quantity": 100 * noise(N, item_id + 7)}
    )


def _ctx(frames, ids, **kw):
    return make_ctx(
        hourly=pd.concat(frames, ignore_index=True),
        items=items_frame([(i, f"Item {i}", 30) for i in ids]),
        snapshot=snapshot_frame({i: 50.0 for i in ids}),
        **kw,
    )


def test_planted_saturday_and_reset():
    res = weekday_reset(_ctx([_saturday_item(1), _reset_item(2), _flat_item(3)], [1, 2, 3]))
    r = res.ranked.set_index("item_id")
    assert list(res.ranked.columns[:2]) == ["item_id", "name"]
    assert res.ranked.iloc[0]["item_id"] in (1, 2)
    sat = r.loc[1]
    assert sat["peak_day"] == "Sat" and sat["weeks"] == 5
    assert 0.1 < sat["amplitude"] < 0.2 and sat["consistency"] == 1.0
    assert abs(r.loc[2, "reset_change"] - 0.2) < 0.03 and r.loc[2, "resets"] == 5
    assert abs(r.loc[1, "reset_change"]) < 0.05
    assert r.loc[3, "amplitude"] < 0.05
    assert res.items_checked == 3
    assert res.items_hit == 2  # the reset item peaks on Wednesday, too
    assert {"weekday", "market_weekday", "reset"} == set(res.charts)
    assert len(res.charts["market_weekday"]) == 7
    assert set(res.charts["reset"]["reset_at"].dt.day_of_week) == {2}


def test_flat_noise_shows_nothing():
    res = weekday_reset(_ctx([_flat_item(i) for i in (4, 5, 6)], [4, 5, 6]))
    assert res.items_hit == 0
    assert (res.ranked["amplitude"] < 0.05).all()
    assert (res.ranked["reset_change"].abs() < 0.03).all()


def test_empty_input():
    res = weekday_reset(make_ctx())
    assert res.ranked.empty and list(res.ranked.columns[:2]) == ["item_id", "name"]
    assert res.items_checked == 0 and res.charts["reset"].empty


def test_gate_needs_28_days():
    start, end = date(2026, 11, 9), date(2026, 11, 16)
    ctx = make_ctx(hourly=_flat_item(7), start=start, end=end)
    res = run("weekday_reset", ctx)
    assert res.needs_days == 20 and res.ready_on == end + timedelta(days=20)
