from datetime import UTC, date, datetime, timedelta

import pandas as pd

from coppertrail.collector.store import ITEMS, SELECTION, Store
from coppertrail.query import series
from tests.new_archive import hours_from, item_row, make_archive

T0 = datetime(2026, 11, 9, tzinfo=UTC)
ITEMS_ = [(10, "Rugged Leather", "Trade Goods", "COMMON", "Leather", 0, 250, 40)]


def test_hourly_reads_hour_files_in_range(tmp_path):
    data = make_archive(tmp_path, ITEMS_, {10: hours_from(T0, 8 * 24, min=30, median=40)})
    h = series.hourly(data, [10], date(2026, 11, 10), date(2026, 11, 11))
    assert len(h) == 48
    assert list(h.columns) == series.HOURLY_COLS
    assert str(h["hour"].dt.tz) == "UTC"
    assert h["hour"].min() == datetime(2026, 11, 10, tzinfo=UTC)
    assert h["hour"].max() == datetime(2026, 11, 11, 23, tzinfo=UTC)
    assert len(series.hourly(data)) == 8 * 24
    assert series.hourly(data, []).empty and series.hourly(data, [999]).empty
    assert series.hourly(data, None, date(2026, 12, 1)).empty
    hs = series.house(data, date(2026, 11, 16))
    assert len(hs) == 24 and hs["units"].tolist() == [10] * 24


def test_items_newest_row_and_placeholder_name(tmp_path):
    data = make_archive(tmp_path, ITEMS_ + [(11, None, None)], {})
    store = Store(data, data / "window")
    newer = item_row((10, "Rugged Leather v2", "Trade Goods"), FETCHED2)
    store.write_day(ITEMS, FETCHED2.date(), pd.DataFrame([newer]))
    it = series.items(data).set_index("item_id")
    assert list(it.reset_index().columns) == series.ITEM_COLS
    assert it.loc[10, "name"] == "Rugged Leather v2"
    assert it.loc[11, "name"] == "#11"
    # item 12 is only in the newest selection, not in the item details
    sel = pd.DataFrame({"day": FETCHED2.date(), "item_id": [10, 12], "reason": "rule"})
    store.write_day(SELECTION, FETCHED2.date(), sel)
    it = series.items(data).set_index("item_id")
    assert it.loc[12, "name"] == "#12" and pd.isna(it.loc[12, "item_class"])
    d = series.item_details(data).set_index("item_id")
    assert d.loc[10, "vendor_price"] == 250 and d.loc[10, "subclass"] == "Leather"


FETCHED2 = datetime(2026, 11, 17, 6, tzinfo=UTC)


def test_latest_per_item_sales_per_day(tmp_path):
    rows = hours_from(T0, 48, min=30, median=40, gone_units=1, partial_units=1, span_hours=1.0)
    data = make_archive(tmp_path, ITEMS_, {10: rows})
    latest = series.latest_per_item(data).set_index("item_id")
    # 48 covered hours, 2 units sold each hour -> 48 units per day
    assert latest.loc[10, "sales_per_day"] == 48.0
    assert latest.loc[10, "observed_at"] == T0 + timedelta(hours=47, minutes=22)


def test_latest_per_item_no_coverage_is_null(tmp_path):
    data = make_archive(tmp_path, ITEMS_, {10: hours_from(T0, 5, min=30, median=40)})
    latest = series.latest_per_item(data)
    assert pd.isna(latest["sales_per_day"].iloc[0])


def test_latest_per_item_medians(tmp_path):
    # 23 days at median 100, then 7 days at median 200; min 50 except one hour at 10
    rows = hours_from(T0, 30 * 24, min=50, median=100, quantity=5)
    for r in rows[23 * 24 :]:
        r["median"] = 200
    rows[30]["min"] = 10
    rows[-1].update(min=60, median=210, quantity=7)
    data = make_archive(tmp_path, ITEMS_, {10: rows})
    latest = series.latest_per_item(data).set_index("item_id")
    assert list(latest.reset_index().columns) == series.LATEST_COLS
    row = latest.loc[10]
    assert row["median"] == 210 and row["min_buyout"] == 60 and row["quantity"] == 7
    assert row["median_7d"] == 200  # median of the hourly medians in the last 7 days
    assert row["median_30d"] == 100
    assert row["low_30d"] == 10 and row["high_30d"] == 60
    assert series.latest_per_item(data, [999]).empty


def test_missing_tables_give_typed_empty_frames(tmp_path):
    h = series.hourly(tmp_path)
    assert h.empty and list(h.columns) == series.HOURLY_COLS
    assert str(h["hour"].dtype).endswith("UTC]")
    assert series.house(tmp_path).empty and "gold_listed" in series.house(tmp_path).columns
    assert series.items(tmp_path).empty and list(series.items(tmp_path).columns) == series.ITEM_COLS
    assert series.item_details(tmp_path).empty
    assert series.recipes(tmp_path).empty and "reagent_qty" in series.recipes(tmp_path).columns
    assert series.builds(tmp_path).empty and "published_at" in series.builds(tmp_path).columns
    latest = series.latest_per_item(tmp_path)
    assert latest.empty and list(latest.columns) == series.LATEST_COLS
    for gone in ("scans", "snapshots", "latest_snapshot", "economy"):
        assert not hasattr(series, gone)


def test_recipes_and_builds_mapped(tmp_path):
    recipes = [
        {
            "recipe_id": 19058,
            "name": "Rugged Armor Kit",
            "profession": "Leatherworking",
            "crafted_item_id": 15564,
            "crafted_qty": 1.0,
            "reagent_id": 10,
            "reagent_qty": 4,
        }
    ]
    b1 = datetime(2026, 11, 1, 12, tzinfo=UTC)
    builds = [
        {
            "version": "1.60.1",
            "build": 70399,
            "namespace": "static-1.60.1_70399-forever-eu",
            "first_seen": b1,
        },
        {
            "version": "1.60.2",
            "build": 70500,
            "namespace": "static-1.60.2_70500-forever-eu",
            "first_seen": FETCHED2,
        },
    ]
    data = make_archive(tmp_path, ITEMS_, {}, recipes=recipes, builds=builds)
    r = series.recipes(data)
    assert list(r.columns) == series.RECIPE_COLS
    row = r.iloc[0]
    assert (row["spell_id"], row["result_id"], row["reagent_id"], row["reagent_qty"]) == (
        19058,
        15564,
        10,
        4,
    )
    assert row["recipe_name"] == "Rugged Armor Kit" and row["reagent_name"] == "Rugged Leather"
    assert row["result_qty_min"] == 1 and row["result_qty_max"] == 1
    b = series.builds(data)
    assert b["build_id"].tolist() == [70399, 70500]
    assert b["version"].tolist() == ["1.60.1", "1.60.2"]
    assert series.builds(data, date(2026, 11, 10), date(2026, 11, 17))["build_id"].tolist() == [
        70500
    ]
    assert str(b["published_at"].dt.tz) == "UTC"
