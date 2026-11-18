from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from coppertrail.collector.sales import (
    MAX_SPAN_HOURS,
    auction_changes,
    compare,
    load_state,
    save_state,
    sold_value,
)

T0 = datetime(2026, 11, 18, 11, 22, 52, tzinfo=UTC)
SALES = ["gone_units", "partial_units", "short_gone_units", "new_units", "span_hours"]


def frame_of_ids(rows):
    """(auction_id, item_id, quantity, time_left[, unit]) rows; unit defaults to 10."""
    full = [(*r, 10.0) if len(r) == 4 else r for r in rows]
    df = pd.DataFrame(full, columns=["auction_id", "item_id", "quantity", "time_left", "unit"])
    return df.astype({"auction_id": "int64", "item_id": "int32", "quantity": "int32"})


PREV = frame_of_ids(
    [(1, 10, 5, "LONG", 7.0), (2, 10, 3, "SHORT"), (3, 10, 4, "MEDIUM", 11.0), (4, 20, 9, "LONG")]
)
CUR = frame_of_ids([(3, 10, 1, "MEDIUM"), (4, 20, 9, "LONG"), (5, 20, 2, "VERY_LONG")])


def test_gone_short_partial_new():
    r = compare(PREV, CUR, T0, T0 + timedelta(hours=1)).set_index("item_id")
    cols = ["gone_units", "short_gone_units", "partial_units", "new_units"]
    assert r.loc[10, cols].tolist() == [5, 3, 3, 0]
    assert r.loc[20, ["gone_units", "new_units"]].tolist() == [0, 2]
    assert r.loc[10, "span_hours"] == 1.0


def test_items_from_both_snapshots():
    prev = frame_of_ids([(1, 30, 2, "LONG")])
    cur = frame_of_ids([(2, 40, 1, "LONG")])
    r = compare(prev, cur, T0, T0 + timedelta(hours=1)).set_index("item_id")
    assert sorted(r.index) == [30, 40]
    assert r.loc[30, "gone_units"] == 2 and r.loc[40, "new_units"] == 1
    assert r.loc[30, "new_units"] == 0 and r.loc[40, "gone_units"] == 0


def test_quantity_rise_is_not_partial():
    prev = frame_of_ids([(1, 10, 2, "LONG")])
    cur = frame_of_ids([(1, 10, 3, "LONG")])
    assert compare(prev, cur, T0, T0 + timedelta(hours=1)).iloc[0]["partial_units"] == 0


def test_two_hour_span_kept():
    r = compare(PREV, CUR, T0, T0 + timedelta(hours=2)).set_index("item_id")
    assert r.loc[10, "span_hours"] == 2.0 and r.loc[10, "gone_units"] == 5


def test_no_prev_or_too_old_is_null():  # Review Focus 3
    r = compare(None, CUR, None, T0)
    assert sorted(r["item_id"]) == [10, 20]
    assert r[SALES].isna().all().all()
    late = compare(PREV, CUR, T0, T0 + timedelta(hours=MAX_SPAN_HOURS + 1))
    assert late[SALES].isna().all().all()
    assert compare(PREV, CUR, T0, T0)[SALES].isna().all().all()  # span 0
    edge = compare(PREV, CUR, T0, T0 + timedelta(hours=MAX_SPAN_HOURS))
    assert edge["span_hours"].notna().all()


def test_sold_value():
    # auction 1 gone (5 x 7), auction 2 gone but SHORT (left out), auction 3 dropped 3 (3 x 11)
    assert sold_value(PREV, CUR) == 5 * 7 + 3 * 11


def test_sold_value_nan_unit_counts_zero():
    prev = frame_of_ids([(1, 10, 5, "LONG", np.nan), (2, 10, 1, "LONG", 4.0)])
    assert sold_value(prev, frame_of_ids([])) == 4


def test_auction_changes():
    assert auction_changes(PREV, CUR) == (2, 1)  # auctions 1 and 2 gone, 5 new


def test_state_round_trip(tmp_path):
    path = tmp_path / "state" / "listings.parquet"
    save_state(path, CUR.assign(kind="item"), T0, house=111)
    frame, at = load_state(path, 111, T0 + timedelta(hours=1), copied_days=30)
    assert at == T0
    assert list(frame.columns) == ["auction_id", "item_id", "quantity", "time_left", "unit"]
    assert frame["auction_id"].tolist() == [3, 4, 5]
    meta = pq.read_schema(path).metadata
    assert meta[b"house"] == b"111"


def test_state_missing_is_none(tmp_path):
    assert load_state(tmp_path / "nope.parquet", 111, T0, 30) is None


def test_state_other_house_ignored(tmp_path):
    path = tmp_path / "listings.parquet"
    save_state(path, CUR, T0, house=111)
    assert load_state(path, 110, T0 + timedelta(hours=1), 30) is None
    assert not path.exists()


def test_state_older_than_copied_days_deleted(tmp_path):
    path = tmp_path / "listings.parquet"
    save_state(path, CUR, T0, house=111)
    assert load_state(path, 111, T0 + timedelta(days=30, seconds=1), 30) is None
    assert not path.exists()


def test_state_unreadable_deleted(tmp_path):
    path = tmp_path / "listings.parquet"
    path.write_bytes(b"not parquet")
    assert load_state(path, 111, T0, 30) is None
    assert not path.exists()
