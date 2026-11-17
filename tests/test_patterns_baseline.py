import pandas as pd
import pytest

from coppertrail.patterns import baseline as B


def _series(days: int = 8, evening: int = 100, morning: int = 120) -> pd.DataFrame:
    """One item, flat 110 except a cheap CET evening and a dear CET morning."""
    hours = pd.date_range("2026-11-08 23:00", periods=days * 24, freq="h", tz="UTC")
    local = hours.tz_convert(B.TZ).hour
    price = [evening if h in B.EVENING else morning if h in B.MORNING else 110 for h in local]
    qty = [200 if h == 22 else 100 for h in local]
    return pd.DataFrame({"item_id": 1, "hour": hours, "min": price, "p25": price, "quantity": qty})


def test_trim_mean_drops_tails():
    assert B.trim_mean(pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 1000])) == pytest.approx(5.5)


def test_flip_return_after_cut():
    nights = B.flip(_series())
    # 9 Nov 00:00 CET belongs to the evening of 8 Nov; the last evening has no morning
    assert len(nights) == 8
    assert nights["ret_min"].tolist() == pytest.approx([120 * 0.95 / 100 - 1] * 8)
    s = B.flip_summary(nights, pd.DataFrame({"item_id": [1], "name": ["X"]}))
    assert s["positive"] == 1 and s["robust"] == ["X"]


def test_rhythm_finds_the_planted_hours():
    r = B.rhythm(_series()).set_index("hour")
    assert r["quantity"].idxmax() == 22
    assert r["min"].idxmin() in B.EVENING
    assert r["min"].idxmax() in B.MORNING


def test_trend_uses_full_days():
    h = _series()
    h.loc[h["hour"] >= "2026-11-15 23:00", "quantity"] *= 2  # last CET day doubles
    t = B.trend(h, pd.DataFrame({"item_id": [1], "name": ["X"]}))
    assert t["median_quantity"] == pytest.approx(100.0)
