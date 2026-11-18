from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
from blizzard_fixtures import item_detail, mock_transport

from coppertrail.collector.blizzard import BlizzardClient
from coppertrail.collector.config import Blizzard
from coppertrail.collector.master import (
    known_items,
    refresh_items,
    refresh_recipes,
    stale_items,
)
from coppertrail.collector.store import ITEMS, RECIPES, Store

CFG = Blizzard(rate_per_s=1e9)
NOW = datetime(2026, 11, 19, 0, 50, tzinfo=UTC)


def client(routes, calls=None):
    return BlizzardClient(
        CFG, "id", "secret", transport=mock_transport(routes, calls), sleep=lambda s: None
    )


def item_route(detail, namespace="static-1.60.1_70399-forever-eu", only_ns="static-forever-eu"):
    def handle(req):
        if req.url.params["namespace"] != only_ns:
            return httpx.Response(404)
        return httpx.Response(200, json=detail, headers={"battlenet-namespace": namespace})

    return handle


def store(tmp_path):
    return Store(tmp_path, tmp_path / "window")


def test_refresh_items_maps_fields(tmp_path):
    s = store(tmp_path)
    detail = item_detail(
        4306, quality="UNCOMMON", cls="Trade Goods", cls_id=7, sub="Cloth", sub_id=5, sell=150
    )
    with client({"/data/wow/item/4306": item_route(detail)}) as c:
        assert refresh_items(c, s, [4306], NOW) == 1
    assert s.path(ITEMS, NOW.date()).exists()
    row = known_items(s).set_index("item_id").loc[4306]
    assert row["found"]
    assert (row["name"], row["quality"], row["class"], row["subclass"]) == (
        "Item 4306",
        "UNCOMMON",
        "Trade Goods",
        "Cloth",
    )
    assert (row["class_id"], row["subclass_id"], row["sell_price"], row["purchase_price"]) == (
        7,
        5,
        150,
        600,
    )
    assert (row["item_level"], row["required_level"]) == (5, 0)
    assert row["namespace"] == "static-1.60.1_70399-forever-eu"
    assert row["fetched_at"] == NOW


def test_classic1x_fallback_namespace_kept(tmp_path):
    s = store(tmp_path)
    route = item_route(
        item_detail(2589), namespace="static-classic1x-eu", only_ns="static-classic1x-eu"
    )
    with client({"/data/wow/item/2589": route}) as c:
        refresh_items(c, s, [2589], NOW)
    assert known_items(s).iloc[0]["namespace"] == "static-classic1x-eu"


def test_unknown_item_stored_as_not_found(tmp_path):
    s = store(tmp_path)
    with client({}) as c:
        assert refresh_items(c, s, [999999], NOW) == 1
    row = known_items(s).iloc[0]
    assert row["item_id"] == 999999 and not row["found"] and pd.isna(row["name"])


def test_newest_row_wins(tmp_path):
    s = store(tmp_path)
    earlier = NOW - timedelta(days=2)
    with client({"/data/wow/item/10": item_route(item_detail(10, quality="COMMON"))}) as c:
        refresh_items(c, s, [10, 11], earlier)
    with client({"/data/wow/item/10": item_route(item_detail(10, quality="RARE"))}) as c:
        refresh_items(c, s, [10], NOW)
        refresh_items(c, s, [10], NOW + timedelta(minutes=5))  # same day: merged, not duplicated
    k = known_items(s).set_index("item_id")
    assert len(k) == 2
    assert k.loc[10, "quality"] == "RARE" and k.loc[10, "fetched_at"] == NOW + timedelta(minutes=5)
    assert k.loc[11, "fetched_at"] == earlier
    today = pd.read_parquet(s.path(ITEMS, NOW.date()))
    assert today["item_id"].tolist() == [10]


def test_known_items_empty(tmp_path):
    k = known_items(store(tmp_path))
    assert k.empty and "item_id" in k.columns and "found" in k.columns


def test_stale_items(tmp_path):
    s = store(tmp_path)

    def row(item_id, found, age_days):
        return {"item_id": item_id, "found": found, "fetched_at": NOW - timedelta(days=age_days)}

    rows = [row(1, True, 8), row(2, True, 2), row(3, False, 2), row(4, False, 0.5)]
    for r in rows:
        s.write_day(ITEMS, r["fetched_at"].date(), pd.DataFrame([r]))
    assert stale_items(s, NOW) == [1, 3]


def test_recipes_walk_skips_dnt(tmp_path):
    s = store(tmp_path)
    calls = []

    def js(body):
        return lambda req: httpx.Response(200, json=body)

    routes = {
        "/data/wow/profession/index": js(
            {
                "professions": [
                    {"id": 197, "name": "Tailoring"},
                    {"id": 999, "name": "Test Profession [DNT]"},
                ]
            }
        ),
        "/data/wow/profession/197": js(
            {"id": 197, "name": "Tailoring", "skill_tiers": [{"id": 2948, "name": "Tailoring"}]}
        ),
        "/data/wow/profession/197/skill-tier/2948": js(
            {
                "categories": [
                    {"name": "Cloth", "recipes": [{"id": 2359, "name": "Bolt of Linen Cloth"}]},
                    {"name": "Misc", "recipes": [{"id": 2360, "name": "Learning"}]},
                ]
            }
        ),
        "/data/wow/recipe/2359": js(
            {
                "id": 2359,
                "name": "Bolt of Linen Cloth",
                "crafted_item": {"id": 2996},
                "crafted_quantity": {"value": 1.0},
                "reagents": [
                    {"reagent": {"id": 2589}, "quantity": 2},
                    {"reagent": {"id": 2320}, "quantity": 1},
                ],
            }
        ),
        "/data/wow/recipe/2360": js({"id": 2360, "name": "Learning"}),
    }
    with client(routes, calls) as c:
        assert refresh_recipes(c, s, NOW) == 2
    assert not any("/profession/999" in r.url.path for r in calls)
    df = pd.read_parquet(s.path(RECIPES, NOW.date())).sort_values(["recipe_id", "reagent_id"])
    with_reagents = df[df["recipe_id"] == 2359]
    assert sorted(zip(with_reagents["reagent_id"], with_reagents["reagent_qty"], strict=True)) == [
        (2320, 1),
        (2589, 2),
    ]
    assert set(with_reagents["crafted_item_id"]) == {2996} and set(
        with_reagents["crafted_qty"]
    ) == {1.0}
    assert set(with_reagents["profession"]) == {"Tailoring"}
    bare = df[df["recipe_id"] == 2360]
    assert (
        len(bare) == 1
        and pd.isna(bare.iloc[0]["reagent_id"])
        and pd.isna(bare.iloc[0]["crafted_item_id"])
    )
