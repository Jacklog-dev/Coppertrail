"""Item details (subclass, vendor price), recipes and builds."""

from datetime import UTC, datetime, timedelta

import httpx
from test_run import MARKET, NOW, FakeApi, make

from coppertrail.collector.legacy import parse
from coppertrail.collector.legacy.run import EXIT_OK
from coppertrail.collector.legacy.store import BUILDS, ITEMS, RECIPES, RUNS

FETCHED = datetime(2026, 11, 17, 14, 0, tzinfo=UTC)

ITEM_2318 = {
    "id": 2318,
    "name": "Light Leather",
    "quality": "COMMON",
    "itemClass": "Trade Goods",
    "itemSubclass": "Leather",
    "level": 10,
    "requiredLevel": None,
    "vendorSell": 15,
    "icon": "https://render.worldofwarcraft.com/x.jpg",
}

CRAFTING = {
    "market": MARKET,
    "recipes": [
        {
            "recipe": {
                "spellId": 19058,
                "name": "Rugged Armor Kit",
                "profession": "Leatherworking",
                "skillRequired": 185,
                "acquisition": "trainer",
            },
            "result": {"id": 15564, "name": "Rugged Armor Kit", "qtyMin": 1, "qtyMax": 1},
            "resultPrice": 12500,
            "reagents": [{"id": 8170, "name": "Rugged Leather", "qty": 5, "price": 1495}],
            "unpriced": [],
        },
        {
            "recipe": {
                "spellId": 3816,
                "name": "Cured Light Hide",
                "profession": "Leatherworking",
                "skillRequired": 10,
                "acquisition": "trainer",
            },
            "result": {"id": 4231, "name": "Cured Light Hide", "qtyMin": 1, "qtyMax": 1},
            "reagents": [
                {"id": 783, "name": "Light Hide", "qty": 1, "price": 130},
                {"id": 4289, "name": "Salt", "qty": 1, "price": None},
            ],
            "unpriced": [],
        },
    ],
}

BUILDS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>AHledger · WoW Forever build changes</title>
    <item>
      <title>WoW Forever 1.60.1 (build 70938): 20 removed, 2 renamed or changed</title>
      <link>https://ahledger.com/wow-forever/changes/WOW-70938patch1.60.1_Retail</link>
      <guid isPermaLink="true">https://ahledger.com/wow-forever/changes/WOW-70938patch1.60.1_Retail</guid>
      <pubDate>Fri, 13 Nov 2026 02:38:25 GMT</pubDate>
      <description>20 removed, 2 renamed or changed.</description>
    </item>
    <item>
      <title>WoW Forever pre-launch patch 1.60.1 (build 70755): 39 items added</title>
      <link>https://ahledger.com/wow-forever/changes/WOW-70755</link>
      <pubDate>Tue, 03 Nov 2026 10:00:00 GMT</pubDate>
      <description>39 items added.</description>
    </item>
    <item>
      <title>Something else entirely</title>
      <link>https://ahledger.com/wow-forever/changes/other</link>
      <pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


# Parsing ---------------------------------------------------------------------


def test_item_detail_row():
    row = parse.item_detail_row(ITEM_2318, FETCHED)
    assert row == {
        "item_id": 2318,
        "name": "Light Leather",
        "quality": "COMMON",
        "item_class": "Trade Goods",
        "subclass": "Leather",
        "level": 10,
        "required_level": None,
        "vendor_price": 15,
        "fetched_at": FETCHED,
        "source": "api",
    }


def test_tooltip_rows_leave_details_empty():
    row = parse.item_rows({"items": [{"id": 1, "name": "x"}]}, FETCHED)[0]
    assert row["subclass"] is None and row["vendor_price"] is None


def test_recipe_rows_one_per_reagent():
    rows = parse.recipe_rows(CRAFTING, FETCHED, "r1")
    assert len(rows) == 3
    kit = rows[0]
    assert kit == {
        "spell_id": 19058,
        "recipe_name": "Rugged Armor Kit",
        "profession": "Leatherworking",
        "skill_required": 185,
        "acquisition": "trainer",
        "result_id": 15564,
        "result_name": "Rugged Armor Kit",
        "result_qty_min": 1,
        "result_qty_max": 1,
        "reagent_id": 8170,
        "reagent_name": "Rugged Leather",
        "reagent_qty": 5,
        "source": "api",
        "run_id": "r1",
        "fetched_at": FETCHED,
    }
    assert [(r["spell_id"], r["reagent_id"], r["reagent_qty"]) for r in rows[1:]] == [
        (3816, 783, 1),
        (3816, 4289, 1),
    ]


def test_recipe_without_reagents_keeps_one_row():
    payload = {"recipes": [{**CRAFTING["recipes"][0], "reagents": []}]}
    rows = parse.recipe_rows(payload, FETCHED, "r1")
    assert len(rows) == 1 and rows[0]["reagent_id"] is None


def test_build_rows():
    rows = parse.build_rows(BUILDS_XML, FETCHED, "r1")
    assert len(rows) == 3
    assert rows[0] == {
        "build_id": 70938,
        "version": "1.60.1",
        "stage": None,
        "title": "WoW Forever 1.60.1 (build 70938): 20 removed, 2 renamed or changed",
        "published_at": datetime(2026, 11, 13, 2, 38, 25, tzinfo=UTC),
        "url": "https://ahledger.com/wow-forever/changes/WOW-70938patch1.60.1_Retail",
        "description": "20 removed, 2 renamed or changed.",
        "source": "api",
        "run_id": "r1",
        "fetched_at": FETCHED,
    }
    assert (rows[1]["build_id"], rows[1]["stage"]) == (70755, "pre-launch patch")
    assert rows[2]["build_id"] is None and rows[2]["version"] is None


# Runs ------------------------------------------------------------------------


class MasterApi(FakeApi):
    def __init__(self, missing_items=(), **kw):
        super().__init__(**kw)
        self.missing_items = set(missing_items)

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.url.host == "api.ahledger.com" and path.startswith("/v1/items/"):
            self.calls.append((path, None))
            iid = int(path.rsplit("/", 1)[1])
            if iid in self.missing_items or req.url.params.get("game") != "forever":
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(
                200,
                json={**ITEM_2318, "id": iid, "name": f"Item {iid}", "vendorSell": iid * 10},
            )
        if path == f"/v1/crafting/{MARKET}":
            self.calls.append((path, None))
            assert req.url.params["all"] == "true" and req.url.params["limit"] == "3000"
            return httpx.Response(200, json=CRAFTING)
        if req.url.host == "ahledger.com" and path == "/feed/builds.xml":
            self.calls.append((path, None))
            return httpx.Response(
                200, headers={"Content-Type": "application/rss+xml"}, text=BUILDS_XML
            )
        return super().__call__(req)


def _latest_items(store):
    rows = store.read_all(ITEMS).sort_by("fetched_at").to_pylist()
    return {r["item_id"]: r for r in rows}


def test_run_stores_details_recipes_builds(tmp_path):
    api = MasterApi()
    assert make(tmp_path, api).run() == EXIT_OK
    st = make(tmp_path, api).store
    items = _latest_items(st)
    assert {i: (r["subclass"], r["vendor_price"]) for i, r in items.items()} == {
        1: ("Leather", 10),
        2: ("Leather", 20),
        50: ("Leather", 500),
        3: (None, None),  # POOR, not on the watchlist: tooltip row only
    }
    rec = st.read_all(RECIPES)
    assert rec.num_rows == 3 and set(rec.column("source").to_pylist()) == {"api"}
    builds = st.read_all(BUILDS)
    assert sorted(builds.column("build_id").to_pylist(), key=str) == [70755, 70938, None]
    assert len(st.day_files(BUILDS)) == 3  # one per publish day
    run = st.read_all(RUNS).to_pylist()[0]
    assert run["status"] == "ok"


def test_rerun_skips_known_details_and_keeps_files(tmp_path):
    api = MasterApi()
    make(tmp_path, api).run()
    st = make(tmp_path, api).store
    mtimes = {p: p.stat().st_mtime_ns for t in (RECIPES, BUILDS) for p in st.day_files(t)}
    api.calls.clear()
    make(tmp_path, api, now=NOW + timedelta(minutes=5)).run()
    assert not [p for p, _ in api.calls if p.startswith("/v1/items/")]
    assert {p: p.stat().st_mtime_ns for p in mtimes} == mtimes
    assert st.read_all(RECIPES).num_rows == 3
    assert st.read_all(BUILDS).num_rows == 3


def test_details_cap_and_missing_item(tmp_path):
    api = MasterApi(missing_items={1})
    make(tmp_path, api, item_details_per_run=1).run()
    st = make(tmp_path, api).store
    assert _latest_items(st)[2]["vendor_price"] == 20  # rank 0 first
    assert _latest_items(st)[1]["vendor_price"] is None
    api.calls.clear()
    make(tmp_path, api, now=NOW + timedelta(minutes=5), item_details_per_run=5).run()
    asked = [p for p, _ in api.calls if p.startswith("/v1/items/")]
    assert asked == ["/v1/items/1", "/v1/items/50"]  # 1 was a 404 last time: asked again
    assert _latest_items(st)[50]["vendor_price"] == 500


def test_recipes_and_builds_are_soft_errors(tmp_path):
    api = FakeApi()  # no crafting (404) and ahledger.com answers 429 with HTML
    assert make(tmp_path, api).run() == EXIT_OK
    st = make(tmp_path, api).store
    run = st.read_all(RUNS).to_pylist()[0]
    assert run["status"] == "ok"
    assert "recipes failed" in run["notes"] and "builds feed skipped" in run["notes"]
    assert st.read_all(RECIPES) is None and st.read_all(BUILDS) is None
    feed_calls = [p for p, _ in api.calls if p == "/feed/builds.xml"]
    assert len(feed_calls) == 1  # no retries against the website


def test_rfc822_without_zone_is_utc():
    assert parse._rfc822_utc("Fri, 13 Nov 2026 02:38:25 -0000") == datetime(
        2026, 11, 13, 2, 38, 25, tzinfo=UTC
    )


def test_resumed_details_respect_cap_and_skip_staged(tmp_path):
    api = MasterApi()
    c = make(tmp_path, api, item_details_per_run=2)
    from coppertrail.collector.legacy.run import RunState

    c.state = RunState(run_id="20261116T200000Z", started_at=NOW.isoformat())
    c.store.run_dir(c.state.run_id).mkdir(parents=True)
    c._sync_stats()
    watch = c._watchlist(c.state, NOW)  # ranks: 2, 1, 50
    c._item_details(c.state, watch[:1], NOW)  # item 2 staged, then the process "died"
    api.calls.clear()
    c._item_details(c.state, watch, NOW)
    assert [p for p, _ in api.calls if p.startswith("/v1/items/")] == ["/v1/items/1"]


def test_detailed_items_skip_tooltip_and_failures_are_noted(tmp_path):
    api = MasterApi(missing_items={1})
    make(tmp_path, api).run()
    st = make(tmp_path, api).store
    assert "item details failed for 1 items" in st.read_all(RUNS).to_pylist()[0]["notes"]
    api.calls.clear()
    make(tmp_path, api, now=NOW + timedelta(days=1)).run()
    tips = [p for p, _ in api.calls if "/tooltip/" in p]
    assert tips == []  # 2 and 50 have detail rows, 1 and 3 have tooltip qualities
    assert _latest_items(st)[2]["vendor_price"] == 20
