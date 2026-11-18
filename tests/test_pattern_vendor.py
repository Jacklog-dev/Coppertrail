from datetime import date

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, local_hours, make_ctx, noise

from coppertrail.patterns.base import run
from coppertrail.patterns.vendor import vendor_floor
from coppertrail.query.series import DETAIL_COLS, LATEST_COLS

START = "2026-11-08 23:00"  # 00:00 CET on 9 Nov
N = 3 * 24
VENDOR = 1000.0


def _details(prices):
    return pd.DataFrame(
        [
            {"item_id": i, "subclass": "Leather", "required_level": 0, "vendor_price": v}
            for i, v in prices.items()
        ],
        columns=DETAIL_COLS,
    )


def _latest(mins):
    return pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-11-11 22:00", tz="UTC"),
                "item_id": i,
                "sales_per_day": 50.0,
                "min_buyout": m,
            }
            for i, m in mins.items()
        ],
        columns=LATEST_COLS,
    )


def _flat(item_id, level):
    return hourly_frame(item_id, START, {"min": level * noise(N, item_id, 0.02)})


def _dipping(item_id):
    """1.5x the vendor price, but 90 % of it at 20-22 CET on day 1 and 21 CET on day 2."""
    df = _flat(item_id, 1.5 * VENDOR)
    hod = local_hours(START, N)
    day = np.arange(N) // 24
    dip = ((day == 0) & np.isin(hod, [20, 21, 22])) | ((day == 1) & (hod == 21))
    df.loc[dip, "min"] = 0.9 * VENDOR
    return df, int(dip.sum()), df["hour"][dip].max()


def _ctx(frames, ids, details, latest=None, **kw):
    return make_ctx(
        hourly=pd.concat(frames, ignore_index=True),
        items=items_frame([(i, f"Item {i}", 10) for i in ids]),
        latest=_latest({i: 1600.0 for i in ids}) if latest is None else latest,
        details=details,
        **kw,
    )


def test_planted_dip_below_vendor_price():
    dip, n_dip, last = _dipping(1)
    ctx = _ctx(
        [dip, _flat(2, 3 * VENDOR), _flat(3, 1.2 * VENDOR), _flat(4, 500.0)],
        [1, 2, 3, 4],
        _details({1: VENDOR, 2: VENDOR, 4: 0}),  # 3 has no details, 4 a zero price
    )
    res = vendor_floor(ctx)
    assert res.items_checked == 2 and res.items_hit == 1
    assert "2 items skipped: no vendor price" in res.note
    r = res.ranked
    assert list(r.columns[:2]) == ["item_id", "name"]
    assert list(r["item_id"]) == [1, 2]  # lowest ratio first
    top = r.iloc[0]
    assert top["hours_near"] == n_dip and top["hours_below"] == n_dip
    assert top["hours"] == N and abs(top["share_near"] - n_dip / N) < 1e-9
    assert abs(top["lowest_ratio"] - 0.9) < 1e-9
    assert top["best_hour"] == 21
    assert top["last_near_at"] == last
    assert top["min_now"] == 1600.0 and abs(top["ratio_now"] - 1.6) < 1e-9
    assert top["sales_per_day"] == 50.0
    other = r.iloc[1]
    assert other["hours_near"] == 0 and pd.isna(other["last_near_at"])
    assert np.isnan(other["best_hour"]) and other["lowest_ratio"] > 2.5
    hours = res.charts["hours"]
    assert set(hours["item_id"]) == {1, 2}
    assert hours["below"].sum() == n_dip
    bh = res.charts["by_hour"].set_index("hour")["events"]
    assert len(bh) == 24 and bh[21] == 2 and bh[20] == 1 and bh.sum() == n_dip


def test_flat_noise_above_vendor_price_has_no_hits():
    ids = list(range(5, 10))
    res = vendor_floor(
        _ctx([_flat(i, 3 * VENDOR) for i in ids], ids, _details(dict.fromkeys(ids, VENDOR)))
    )
    assert res.items_checked == 5 and res.items_hit == 0
    assert res.charts["by_hour"]["events"].sum() == 0
    assert "skipped" not in res.note


def test_min_now_falls_back_to_last_hourly_min():
    df = _flat(1, 2 * VENDOR)
    res = vendor_floor(_ctx([df], [1], _details({1: VENDOR}), latest=_latest({})))
    assert res.ranked.iloc[0]["min_now"] == df["min"].iloc[-1]


def test_no_vendor_prices_yet():
    res = vendor_floor(_ctx([_flat(1, VENDOR)], [1], None))
    assert res.items_checked == 0 and res.ranked.empty
    assert "No vendor prices yet" in res.note and "1 items skipped" in res.note
    assert set(res.charts) == {"hours", "by_hour"}


def test_empty_hourly():
    res = vendor_floor(make_ctx(details=_details({1: VENDOR})))
    assert res.items_checked == 0 and res.ranked.empty
    assert len(res.charts["by_hour"]) == 24


def test_gate_on_empty_archive():
    import coppertrail.patterns.vendor  # noqa: F401  (registers the job)

    ctx = make_ctx(start=date(2026, 11, 9), end=date(2026, 11, 9))
    ctx.__dict__["span"] = (None, None)
    res = run("vendor_floor", ctx)
    assert res.needs_days == 1 and res.ready_on == date(2026, 11, 10)


def test_items_without_hourly_data_checked_on_latest():
    # 1 has hourly data far above the floor; 2 and 3 only have a latest row.
    ctx = _ctx(
        [_flat(1, 3 * VENDOR)],
        [1, 2, 3],
        _details({1: VENDOR, 2: VENDOR, 3: VENDOR}),
        latest=_latest({1: 3 * VENDOR, 2: 0.95 * VENDOR, 3: 5 * VENDOR}),
    )
    res = vendor_floor(ctx)
    r = res.ranked.set_index("item_id")
    assert res.items_checked == 3 and res.items_hit == 1
    assert res.ranked["item_id"].iloc[0] == 2
    assert r.loc[2, "hours"] == 0 and np.isclose(r.loc[2, "ratio_now"], 0.95)
    assert pd.notna(r.loc[2, "last_near_at"]) and pd.isna(r.loc[3, "last_near_at"])
    assert "2 items without hourly data" in res.note
