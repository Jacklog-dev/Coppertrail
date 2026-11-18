import sys
import types
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
import pyarrow.parquet as pq
import pytest
from blizzard_fixtures import commodity, http_date, item_auction, mock_transport

from coppertrail.collector import hourly
from coppertrail.collector.blizzard import BlizzardClient
from coppertrail.collector.config import load_config
from coppertrail.collector.store import BUILDS, HOURLY, HOUSE, ITEMS, SELECTION, Store

T0 = datetime(2026, 11, 18, 11, 22, 52, tzinfo=UTC)
INDEX = "/data/wow/ruleset/2/auctions/"
ITEMS_PATH = "/data/wow/ruleset/2/auctions/111"
COMMS_PATH = "/data/wow/ruleset/2/auctions/111/commodities"
CLASS_INDEX = "/data/wow/item-class/index"
NAMESPACE = "static-1.60.1_70399-forever-eu"

# item 10: common trade good (selected), 20: grey junk (not selected), 30: unknown to Blizzard
DETAILS = {
    10: {"found": True, "quality": "COMMON", "class": "Trade Goods"},
    20: {"found": True, "quality": "POOR", "class": "Junk"},
}


class House:
    """A mutable fake auction house: tests change the snapshot between runs."""

    def __init__(self, name="Alliance", status=200):
        self.name = name
        self.status = status
        self.at = T0
        self.namespace = NAMESPACE
        self.items = [
            item_auction(1, 10, 5, buyout=500, time_left="LONG"),
            item_auction(2, 20, 1, buyout=3, time_left="LONG"),
        ]
        self.commodities = [commodity(3, 10, 4, 120, time_left="SHORT"), commodity(4, 30, 2, 80)]

    def _listing(self, body):
        def handle(req):
            if self.status == 304:
                return httpx.Response(304)
            headers = {"last-modified": http_date(self.at)}
            return httpx.Response(200, json={"auctions": body()}, headers=headers)

        return handle

    def routes(self):
        return {
            INDEX: lambda r: httpx.Response(
                200, json={"auctions": [{"id": 111, "name": f"{self.name} Normal"}]}
            ),
            ITEMS_PATH: self._listing(lambda: self.items),
            COMMS_PATH: self._listing(lambda: self.commodities),
            CLASS_INDEX: lambda r: httpx.Response(
                200, json={}, headers={"battlenet-namespace": self.namespace}
            ),
        }


@pytest.fixture
def lookups(monkeypatch):
    """Stand-in for coppertrail.collector.master (WP2): writes DETAILS rows, records ids."""
    seen: list[list[int]] = []

    def refresh_items(client, store, ids, now):
        ids = list(ids)
        seen.append(ids)
        rows = [{"item_id": i, **DETAILS.get(i, {"found": False}), "fetched_at": now} for i in ids]
        path = store.path(ITEMS, now.date())
        old = [pd.read_parquet(path)] if path.exists() else []
        store.write_day(ITEMS, now.date(), pd.concat([*old, pd.DataFrame(rows)]))
        return len(rows)

    fake = types.ModuleType("coppertrail.collector.master")
    fake.refresh_items = refresh_items
    monkeypatch.setitem(sys.modules, "coppertrail.collector.master", fake)
    return seen


def run(tmp_path, house, at=None, sleeps=None, calls=None):
    cfg = load_config(tmp_path)
    sleeps = sleeps if sleeps is not None else []
    client = BlizzardClient(
        cfg.blizzard.__class__(rate_per_s=1e9),
        "id",
        "secret",
        transport=mock_transport(house.routes(), calls),
        sleep=lambda s: None,
    )
    clock = at or (house.at + timedelta(minutes=12))
    with client:
        return hourly.main(cfg, client=client, now=lambda: clock, sleep=sleeps.append)


def store_of(tmp_path):
    return Store(tmp_path, tmp_path / "window")


def hourly_frame(tmp_path, at):
    return pd.read_parquet(store_of(tmp_path).path(HOURLY, at))


def test_first_run_writes_hour_without_sales(tmp_path, lookups):
    house = House()
    assert run(tmp_path, house) == 0
    df = hourly_frame(tmp_path, T0).set_index("item_id")
    assert sorted(df.index) == [10, 30]  # 30 is unclassified, 20 is grey
    row = df.loc[10]
    assert (row["quantity"], row["auctions"], row["min"]) == (9, 2, 100)
    assert row["hour"] == pd.Timestamp("2026-11-18 11:00", tz="UTC")
    assert row["observed_at"] == pd.Timestamp(T0) and row["source"] == "blizzard"
    assert df["gone_units"].isna().all() and df["span_hours"].isna().all()
    assert (tmp_path / ".state" / "listings.parquet").exists()
    sel = pd.read_parquet(store_of(tmp_path).path(SELECTION, T0.date()))
    assert sel.set_index("item_id")["reason"].to_dict() == {10: "rule", 30: "unclassified"}
    assert sorted(lookups[0]) == [10, 20, 30]


def test_second_run_writes_sales(tmp_path, lookups):
    house = House()
    assert run(tmp_path, house) == 0
    house.at = T0 + timedelta(hours=1)
    house.items = [house.items[1]]  # auction 1 (5 of item 10) gone
    house.commodities = [commodity(4, 30, 2, 80), commodity(5, 10, 7, 90)]  # SHORT 3 gone, 5 new
    assert run(tmp_path, house) == 0
    df = hourly_frame(tmp_path, house.at).set_index("item_id")
    r = df.loc[10]
    assert (r["gone_units"], r["short_gone_units"], r["new_units"], r["span_hours"]) == (
        5,
        4,
        7,
        1.0,
    )
    h = pd.read_parquet(store_of(tmp_path).path(HOUSE, house.at)).iloc[0]
    assert h["source"] == "blizzard"
    assert (h["gone_auctions"], h["new_auctions"], h["sold_value_est"]) == (2, 1, 500)
    assert lookups == [[10, 20, 30]]  # nothing new to look up the second time


def test_item_sold_out_keeps_a_row(tmp_path, lookups):
    house = House()
    run(tmp_path, house)
    house.at = T0 + timedelta(hours=1)
    house.commodities = [commodity(3, 10, 4, 120, time_left="SHORT")]  # item 30 sold out
    run(tmp_path, house)
    r = hourly_frame(tmp_path, house.at).set_index("item_id").loc[30]
    assert (r["quantity"], r["auctions"], r["gone_units"]) == (0, 0, 2) and pd.isna(r["median"])


def test_not_modified_exits_0_and_writes_nothing(tmp_path, lookups):
    house = House()
    run(tmp_path, house)
    house.status = 304
    sleeps = []
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*.parquet"))
    assert run(tmp_path, house, at=T0 + timedelta(hours=1), sleeps=sleeps) == 0
    assert sleeps == [60] * 5
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*.parquet")) == before


def test_same_snapshot_twice_is_idempotent(tmp_path, lookups):  # Review Focus 1 and 2
    house = House()
    run(tmp_path, house)
    files = {p: p.read_bytes() for p in tmp_path.rglob("*.parquet")}
    sleeps = []
    assert run(tmp_path, house, sleeps=sleeps) == 0  # 200 with the same Last-Modified
    assert sleeps == [60] * 5
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.parquet")} == files


def test_wrong_house_name_exits_1(tmp_path, lookups):
    assert run(tmp_path, House(name="Horde")) == 1
    assert not list(tmp_path.rglob("*.parquet"))


def test_only_selected_items_written(tmp_path, lookups):
    run(tmp_path, House())
    assert 20 not in set(hourly_frame(tmp_path, T0)["item_id"])
    h = pd.read_parquet(store_of(tmp_path).path(HOUSE, T0)).iloc[0]
    assert (h["auctions"], h["units"], h["gold_listed"]) == (4, 12, 500 + 3 + 480 + 160)
    assert pd.isna(h["gone_auctions"]) and pd.isna(h["sold_value_est"])


def test_existing_selection_is_used(tmp_path, lookups):
    day = T0.date()
    store_of(tmp_path).write_day(
        SELECTION, day, pd.DataFrame({"day": [day], "item_id": [20], "reason": ["rule"]})
    )
    run(tmp_path, House())
    assert hourly_frame(tmp_path, T0)["item_id"].tolist() == [20]


def test_lookups_capped_after_first_run(tmp_path, lookups, monkeypatch):
    monkeypatch.setattr(hourly, "LOOKUP_LIMIT", 1)
    house = House()
    run(tmp_path, house)  # first run: no selection yet, so every unknown id is looked up
    house.at = T0 + timedelta(hours=1)
    house.commodities.append(commodity(6, 40, 1, 9))
    house.commodities.append(commodity(7, 50, 1, 9))
    run(tmp_path, house)
    assert len(lookups[0]) == 3 and lookups[1] == [40]


def test_build_parsed_from_namespace():
    assert hourly.parse_namespace("static-1.60.1_70399-forever-eu") == ("1.60.1", 70399)
    assert hourly.parse_namespace("static-forever-eu") == (None, None)


def test_build_row_written_once_per_namespace(tmp_path, lookups):
    house = House()
    run(tmp_path, house)
    house.at = T0 + timedelta(hours=1)
    run(tmp_path, house)
    house.at = T0 + timedelta(hours=2)
    house.namespace = "static-1.60.2_70500-forever-eu"
    run(tmp_path, house)
    rows = pq.read_table(store_of(tmp_path).path(BUILDS, T0.date())).to_pandas()
    assert set(rows["source"]) == {"blizzard"}
    assert rows[["version", "build"]].values.tolist() == [["1.60.1", 70399], ["1.60.2", 70500]]
    assert rows["first_seen"].tolist() == [pd.Timestamp(T0), pd.Timestamp(house.at)]
