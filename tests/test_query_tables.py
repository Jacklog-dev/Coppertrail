from datetime import UTC, date, datetime

from coppertrail.collector.store import TABLES, Store, to_arrow
from coppertrail.patterns.base import Context
from coppertrail.query.series import builds, item_details, recipes

T1 = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)


def _item(item_id, fetched_at, vendor=None, subclass=None):
    return {
        "item_id": item_id,
        "name": "Rugged Leather",
        "quality": "COMMON",
        "item_class": "Trade Goods",
        "level": 50,
        "fetched_at": fetched_at,
        "source": "api",
        "subclass": subclass,
        "required_level": None,
        "vendor_price": vendor,
    }


def test_empty_tables_give_typed_frames(tmp_path):
    assert recipes(tmp_path).empty and "reagent_qty" in recipes(tmp_path).columns
    assert builds(tmp_path).empty and "published_at" in builds(tmp_path).columns
    assert item_details(tmp_path).empty and "vendor_price" in item_details(tmp_path).columns


def test_item_details_old_files_without_detail_columns(archive):
    # The conftest archive was written with null detail columns: no detail rows.
    assert item_details(archive).empty


def test_item_details_keep_newest_non_null(tmp_path):
    store = Store(tmp_path)
    t = TABLES["items"]
    store.upsert(t, to_arrow(t, [_item(8170, T1, vendor=250, subclass="Leather")]))
    store.upsert(t, to_arrow(t, [_item(8170, T2)]))  # newer tooltip row with nulls
    d = item_details(tmp_path)
    assert d["item_id"].tolist() == [8170]
    assert d["vendor_price"].tolist() == [250] and d["subclass"].tolist() == ["Leather"]
    assert d["required_level"].isna().all()


def test_recipes_newest_fetch_wins(tmp_path):
    store = Store(tmp_path)
    t = TABLES["recipes"]
    row = {
        "spell_id": 19058,
        "recipe_name": "Rugged Armor Kit",
        "profession": "Leatherworking",
        "skill_required": 250,
        "acquisition": "trainer",
        "result_id": 15564,
        "result_name": "Rugged Armor Kit",
        "result_qty_min": 1,
        "result_qty_max": 1,
        "reagent_id": 8170,
        "reagent_name": "Rugged Leather",
        "source": "api",
        "run_id": "r",
    }
    store.upsert(t, to_arrow(t, [row | {"reagent_qty": 4, "fetched_at": T1}]))
    store.upsert(t, to_arrow(t, [row | {"reagent_qty": 5, "fetched_at": T2}]))
    r = recipes(tmp_path)
    assert len(r) == 1 and r["reagent_qty"].iloc[0] == 5


def test_builds_in_range(tmp_path):
    store = Store(tmp_path)
    t = TABLES["builds"]
    rows = [
        {
            "build_id": n,
            "version": f"1.60.{n}",
            "stage": "",
            "title": f"WoW Forever 1.60.{n} (build {n})",
            "published_at": at,
            "url": f"https://example.invalid/{n}",
            "description": "",
            "source": "api",
            "run_id": "r",
            "fetched_at": T2,
        }
        for n, at in ((1, datetime(2026, 11, 1, 12, tzinfo=UTC)), (2, T1))
    ]
    store.upsert(t, to_arrow(t, rows))
    assert builds(tmp_path)["build_id"].tolist() == [1, 2]
    assert builds(tmp_path, date(2026, 11, 10), date(2026, 11, 17))["build_id"].tolist() == [2]
    ctx = Context(tmp_path, None, date(2026, 11, 10), date(2026, 11, 17))
    assert ctx.builds["version"].tolist() == ["1.60.2"]


def test_hourly_of_reads_outside_the_selection(archive):
    ctx = Context(archive, [8170], date(2026, 11, 9), date(2026, 11, 16))
    assert ctx.hourly.empty
    assert set(ctx.hourly_of([2318])["item_id"]) == {2318}
    assert set(ctx.snapshot_of([2318, 8170])["item_id"]) == {2318, 8170}
    everything = Context(archive, None, date(2026, 11, 9), date(2026, 11, 16))
    assert len(everything.hourly_of([2318])) == 8 * 24
