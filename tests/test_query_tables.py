from datetime import UTC, date, datetime

import pandas as pd

from coppertrail.collector.store import ITEMS
from coppertrail.patterns.base import Context
from coppertrail.query.series import builds, item_details, recipes, store_of
from tests.new_archive import item_row, make_archive

T1 = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)


def test_empty_tables_give_typed_frames(tmp_path):
    assert recipes(tmp_path).empty and "reagent_qty" in recipes(tmp_path).columns
    assert builds(tmp_path).empty and "published_at" in builds(tmp_path).columns
    assert item_details(tmp_path).empty and "vendor_price" in item_details(tmp_path).columns


def test_item_details_keep_newest_non_null(tmp_path):
    data = make_archive(tmp_path, [], {})
    store = store_of(data)
    old = item_row((8170, "Rugged Leather", "Trade Goods", "COMMON", "Leather", None, 250), T1)
    store.write_day(ITEMS, T1.date(), pd.DataFrame([old]))
    newer = item_row((8170, "Rugged Leather", "Trade Goods"), T2)  # details gone (nulls)
    store.write_day(ITEMS, T2.date(), pd.DataFrame([newer]))
    d = item_details(data)
    assert d["item_id"].tolist() == [8170]
    assert d["vendor_price"].tolist() == [250] and d["subclass"].tolist() == ["Leather"]
    assert d["required_level"].isna().all()


def test_unknown_items_have_no_details(tmp_path):
    data = make_archive(tmp_path, [(5, None, None)], {})
    assert item_details(data).empty


def test_recipes_newest_fetch_wins(tmp_path):
    data = make_archive(tmp_path, [], {})
    store = store_of(data)
    from coppertrail.collector.store import RECIPES

    row = {
        "recipe_id": 19058,
        "name": "Rugged Armor Kit",
        "profession": "Leatherworking",
        "crafted_item_id": 15564,
        "crafted_qty": 1.0,
        "reagent_id": 8170,
    }
    store.write_day(RECIPES, T1.date(), pd.DataFrame([row | {"reagent_qty": 4, "fetched_at": T1}]))
    store.write_day(RECIPES, T2.date(), pd.DataFrame([row | {"reagent_qty": 5, "fetched_at": T2}]))
    r = recipes(data)
    assert len(r) == 1 and r["reagent_qty"].iloc[0] == 5
    assert pd.isna(r["reagent_name"].iloc[0])  # no item details for the reagent


def test_context_builds_in_range(tmp_path):
    b = [
        {
            "version": "1.60.1",
            "build": 1,
            "namespace": "static-1.60.1_1-forever-eu",
            "first_seen": datetime(2026, 11, 1, 12, tzinfo=UTC),
        },
        {
            "version": "1.60.2",
            "build": 2,
            "namespace": "static-1.60.2_2-forever-eu",
            "first_seen": T1,
        },
        # the same namespace seen again later: the first sighting counts
        {
            "version": "1.60.2",
            "build": 2,
            "namespace": "static-1.60.2_2-forever-eu",
            "first_seen": T2,
        },
    ]
    data = make_archive(tmp_path, [], {}, builds=b)
    assert builds(data)["build_id"].tolist() == [1, 2]
    ctx = Context(data, None, date(2026, 11, 10), date(2026, 11, 17))
    assert ctx.builds["version"].tolist() == ["1.60.2"]
    assert ctx.builds["published_at"].tolist() == [pd.Timestamp(T1)]


def test_hourly_of_and_latest_of_read_outside_the_selection(archive):
    ctx = Context(archive, [8170], date(2026, 11, 9), date(2026, 11, 16))
    assert set(ctx.hourly["item_id"]) == {8170}
    assert set(ctx.hourly_of([2318])["item_id"]) == {2318}
    assert set(ctx.latest_of([2318, 8170])["item_id"]) == {2318, 8170}
    assert ctx.latest["sales_per_day"].tolist() == [9_221.0]
    everything = Context(archive, None, date(2026, 11, 9), date(2026, 11, 16))
    assert len(everything.hourly_of([2318])) == 176
    assert everything.house["units"].sum() > 0
