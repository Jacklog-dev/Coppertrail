from datetime import UTC, date, datetime

import pandas as pd
import pyarrow as pa
import pytest

from coppertrail.collector.store import HOURLY, HOUSE, ITEMS, SELECTION, TABLES, Store

T = datetime(2026, 11, 18, 12, 22, 53, tzinfo=UTC)


def hourly_frame(observed_at=T, item_ids=(20, 10)):
    return pd.DataFrame(
        {
            "item_id": list(item_ids),
            "hour": [observed_at.replace(minute=0, second=0)] * len(item_ids),
            "observed_at": [observed_at] * len(item_ids),
            "min": [5, 1],
            "median": [6, 2],
            "quantity": [3, 4],
            "auctions": [1, 2],
            "source": ["blizzard"] * len(item_ids),
        }
    )


def test_hour_path_layout(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    assert s.path(HOURLY, T) == tmp_path / "hourly" / "2026-11-18" / "12.parquet"
    assert s.path(HOUSE, T) == tmp_path / "house" / "2026-11-18" / "12.parquet"
    want = tmp_path / "window" / "blizzard" / "items" / "2026-11-18.parquet"
    assert s.path(ITEMS, T.date()) == want
    assert s.path(SELECTION, T.date()) == tmp_path / "selection" / "2026-11-18.parquet"


def test_write_hour_once(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    p = s.write_hour(HOURLY, T, hourly_frame())
    before = p.read_bytes()
    assert s.write_hour(HOURLY, T, hourly_frame()) is None
    assert p.read_bytes() == before


def test_write_hour_sorts_and_types(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    s.write_hour(HOURLY, T, hourly_frame())
    tbl = s.read(HOURLY)
    assert tbl.column("item_id").to_pylist() == [10, 20]
    assert tbl.schema.field("item_id").type == pa.int32()
    assert tbl.schema.field("min").type == pa.int64()
    assert tbl.column("p25").null_count == 2  # nullable column filled with nulls
    assert tbl.schema.field("hour").type == pa.timestamp("us", tz="UTC")


def test_extra_column_rejected(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    with pytest.raises(ValueError, match="bogus"):
        s.write_hour(HOURLY, T, hourly_frame().assign(bogus=1))


def test_missing_required_column_rejected(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    with pytest.raises(ValueError, match="quantity"):
        s.write_hour(HOURLY, T, hourly_frame().drop(columns=["quantity"]))


def test_files_by_day_range(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    for day in (16, 17, 18):
        t = T.replace(day=day)
        s.write_hour(HOURLY, t, hourly_frame(observed_at=t))
    got = s.files(HOURLY, date(2026, 11, 17), date(2026, 11, 18))
    assert [p.parent.name for p in got] == ["2026-11-17", "2026-11-18"]
    assert len(s.files(HOURLY, None, None)) == 3


def test_write_day_replaces(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    day = date(2026, 11, 18)
    sel = pd.DataFrame({"day": [day], "item_id": [1], "reason": ["rule"], "rank": [None]})
    s.write_day(SELECTION, day, sel)
    s.write_day(SELECTION, day, sel.assign(item_id=[2]))
    assert s.read(SELECTION).column("item_id").to_pylist() == [2]


def test_read_missing_table_is_none(tmp_path):
    assert Store(tmp_path, tmp_path / "window").read(HOUSE) is None


def test_all_tables_have_a_branch():
    assert {t.branch for t in TABLES.values()} == {"main", "window"}
    assert {"hourly", "house", "selection", "builds", "items", "recipes"} == set(TABLES)


def test_copied_tables_sit_under_their_source():
    # Data copied unchanged from a source lives in window/<source>/, so a second
    # source can sit next to it; Coppertrail's own tables name no source folder.
    copied = {n for n, t in TABLES.items() if t.source is not None}
    assert copied == {"items", "recipes"}
    assert all(t.branch == "window" for t in TABLES.values() if t.source is not None)
    assert all(t.branch == "main" for t in TABLES.values() if t.source is None)
    assert {TABLES[n].source for n in copied} == {"blizzard"}


def test_own_tables_fed_by_a_source_record_it():
    for name in ("hourly", "house", "builds"):
        assert "source" in TABLES[name].required, name
