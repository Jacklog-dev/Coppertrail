"""What the page gets from the bridge: the item list and one item's detail."""

from __future__ import annotations

from coppertrail import db
from coppertrail.ui.bridge import Bridge
from tests.test_sync import ROWS, T1, T2, FakePi


def synced(tmp_path, rows=ROWS):
    b = Bridge(tmp_path / "our.sqlite", source=FakePi(rows))
    b.sync_now()
    b.wait(5)
    return b


def test_empty_database(tmp_path):
    b = Bridge(tmp_path / "our.sqlite", source=FakePi([]))
    assert b.items() == {"at": None, "rows": []}
    st = b.status()
    assert st["hours"] == 0 and st["last"] is None and not st["syncing"]
    assert "Blizzard" in st["credit"]


def test_items_lists_the_newest_hour_by_name(tmp_path):
    data = synced(tmp_path).items()
    assert [(r["id"], r["name"], r["copper"]) for r in data["rows"]] == [
        (20, "Copper Ore", 1300),
        (10, "Linen Cloth", 400),
    ]
    assert data["rows"][0]["price"] == {"parts": [(13, "s")], "text": "13s"}
    assert all(r["trade"] for r in data["rows"])  # both fixtures are trade goods
    assert data["at"] == "25 Nov 2026, 12:00"  # 11:00 UTC in Berlin


def test_item_detail_has_price_change_and_hourly_series(tmp_path):
    d = synced(tmp_path).item(10, "7d")
    assert d["name"] == "Linen Cloth" and d["listed"]
    assert d["price"]["text"] == "4s"
    assert d["x"] == [T1, T2] and d["y"] == [300, 400]
    assert d["change"] == {"text": "▲ +33.3 % since 25 Nov 2026, 11:00", "direction": "rise"}
    assert d["low"]["text"] == "3s" and d["high"]["text"] == "4s"


def test_item_not_listed_now(tmp_path):
    d = synced(tmp_path, ROWS[:3]).item(20, "all")  # hour 2 has no commodities
    assert not d["listed"] and d["price"] is None and d["y"] == [1200, None]
    assert d["lastSeen"] == "25 Nov 2026, 11:00"


def test_only_trade_goods_are_marked_trade(tmp_path):
    b = synced(tmp_path)
    con = db.connect(b.path)
    db.set_item(con, 10, "Linen Cloth", "COMMON", 0, T2)  # now a consumable
    con.commit()
    assert {r["id"]: r["trade"] for r in b.items()["rows"]} == {10: False, 20: True}


def test_unknown_item_shows_its_id(tmp_path):
    b = synced(tmp_path)
    con = db.connect(b.path)
    db.add_prices(con, T2, {99: 5})
    con.commit()
    assert b.item(99)["name"] == "Item 99"


def test_range_24h_cuts_the_series(tmp_path):
    b = synced(tmp_path)
    con = db.connect(b.path)
    db.add_prices(con, T2 + 86400, {10: 500})
    con.commit()
    d = b.item(10, "24h")
    assert d["x"] == [T2 + 86400]  # T2 is 24 h back, outside the range


def test_failed_sync_is_reported_not_raised(tmp_path):
    b = Bridge(tmp_path / "our.sqlite", source=FakePi(ROWS, fail_after=1))
    b.sync_now()
    b.wait(5)
    st = b.status()
    assert not st["ok"] and st["message"].startswith("Sync failed")
