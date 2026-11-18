"""Movers & outliers payloads (coppertrail/ui/movers.py and Bridge.movers / mispricings_now)."""

from datetime import UTC, datetime

from test_bridge_views import (
    build_market,
    market,  # noqa: F401 - shared fixture
)

from coppertrail.ui.bridge import Bridge


def NOW():  # noqa: N802
    return datetime(2026, 11, 17, 9, tzinfo=UTC)


def test_movers_week(market, config_dir):  # noqa: F811
    m = Bridge(market, now=NOW).movers("7d")
    assert m["range"] == "7d" and [r["key"] for r in m["ranges"]] == ["24h", "7d", "30d"]
    risers = m["risers"]
    assert risers["sub"] == "9 Nov – 16 Nov 2026 · items with 10+ sales/day"
    names = [r["name"] for r in risers["rows"]]
    assert names == ["Rugged Leather", "Black Lotus"]
    top = risers["rows"][0]
    assert top["id"] == 8170 and top["dir"] == "rise"
    assert top["change"] == {"text": "▲ +50 %", "dir": "rise"}
    assert top["supply"] == "+50 % supply"
    assert top["sales"] == "9,221" and top["price"]["text"] == "15s"
    assert len(top["spark"]) == 8  # one point per full CET day
    assert m["fallers"]["rows"] == [] and m["fallers"]["note"]


def test_movers_day_and_month(market, config_dir):  # noqa: F811
    b = Bridge(market, now=NOW)
    day = b.movers("24h")
    assert day["risers"]["rows"][0]["id"] == 8170
    assert len(day["risers"]["rows"][0]["spark"]) == 24
    month = b.movers("30d")
    assert month["risers"]["sub"].startswith("9 Nov – 16 Nov 2026 · archive starts 9 Nov")
    assert b.movers("bogus")["range"] == "7d"


def test_mispricings_now(tmp_path, config_dir):
    dip = datetime(2026, 11, 16, 20, tzinfo=UTC)

    def plant(hours):
        for r in hours[8170]:
            if r["hour"] == dip:
                r.update(min=300, quantity=40)

    b = Bridge(build_market(tmp_path, plant), now=NOW)
    m = b.mispricings_now(0.7)
    assert m["threshold"] == 0.7
    assert [t["label"] for t in m["thresholds"]] == [
        "below 50 %", "below 60 %", "below 70 %"
    ]  # fmt: skip
    assert m["sub"] == "17 Nov 2026, 00:00 · last 24 h · 1 item"  # newest snapshot, CET
    row = m["rows"][0]
    assert row["id"] == 8170 and row["name"] == "Rugged Leather"
    assert row["group"] == "Leather chain"
    assert row["price"]["text"] == "3s" and row["usual"]["text"] == "15s 10c"  # 6 h median p25
    assert row["discount"] == {"text": "▼ −80 %", "dir": "fall"}
    assert row["range"] == {"low": 1510.0, "high": 1530.0, "usual": 1510.0, "current": 300.0}
    # The newest snapshot is on 17 Nov (CET), so the 16 Nov dip shows its date.
    assert row["qty"] == "40" and row["seen"] == "16 Nov, 21:00"
    assert b.mispricings_now(0.5)["rows"][0]["id"] == 8170  # 20 % of usual: below 50 %
    assert b.mispricings_now(0.1)["threshold"] == 0.7  # unknown thresholds fall back


def test_mispricings_now_empty_archive(tmp_path, config_dir):
    m = Bridge(tmp_path / "none", now=NOW).mispricings_now()
    assert m["rows"] == [] and "scan" not in (m.get("note", "") + m.get("sub", "")).lower()
