from datetime import UTC, date, datetime

from coppertrail.collector.legacy.store import TABLES, Store, to_arrow
from coppertrail.query import series


def test_hourly_range_and_items(archive):
    h = series.hourly(archive, [2318], date(2026, 11, 10), date(2026, 11, 11))
    assert len(h) == 48
    assert str(h["hour"].dt.tz) == "UTC"
    assert h["hour"].min() == datetime(2026, 11, 10, tzinfo=UTC)
    assert h["hour"].max() == datetime(2026, 11, 11, 23, tzinfo=UTC)
    assert list(h.columns) == series.HOURLY_COLS


def test_hourly_all_and_empty_selections(archive):
    assert len(series.hourly(archive)) == 8 * 24
    assert series.hourly(archive, []).empty
    assert series.hourly(archive, [999]).empty
    assert series.hourly(archive, None, date(2026, 12, 1), None).empty


def test_missing_tables_give_typed_empty_frames(tmp_path):
    h = series.hourly(tmp_path)
    assert h.empty and list(h.columns) == series.HOURLY_COLS
    assert str(h["hour"].dtype).endswith("UTC]")
    assert series.scans(tmp_path).empty
    assert series.economy(tmp_path).empty
    assert series.items(tmp_path).empty


def test_latest_snapshot_and_items(archive):
    snap = series.latest_snapshot(archive, [8170])
    assert snap["min_buyout"].tolist() == [1_495]
    it = series.items(archive)
    assert len(it) == 9 and set(series.ITEM_COLS) <= set(it.columns)


def test_economy_by_day(tmp_path):
    store = Store(tmp_path)
    t = datetime(2026, 11, 16, tzinfo=UTC)
    rows = [
        {
            "market": "m",
            "day": date(2026, 11, d),
            "kind": "daily",
            "observed_at": t,
            "value": d * 1000,
            "auctions": d,
            "source": "api",
            "run_id": "r",
            "fetched_at": t,
        }
        for d in (14, 15, 16)
    ]
    store.upsert(TABLES["economy"], to_arrow(TABLES["economy"], rows))
    e = series.economy(tmp_path, date(2026, 11, 15))
    assert e["value"].tolist() == [15_000, 16_000]
