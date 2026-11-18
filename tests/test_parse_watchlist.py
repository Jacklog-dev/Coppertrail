from datetime import UTC, date, datetime

import pytest

from coppertrail.collector.legacy import parse
from coppertrail.collector.legacy.config import Config, check_cutoff, load_config
from coppertrail.collector.legacy.watchlist import build_watchlist, rule_reason

PT = """AHL1|forever/normal/alliance/eu|1794859989|3
8170:1775:1599:5686:1812:1631:500:2143:91368
12360:488984:488000:46:488040:488040:150000:796140:654
99:5::10:::::
"""


def test_parse_pricetable():
    pt = parse.parse_pricetable(PT)
    assert pt.market == "forever.normal.alliance.eu"
    assert pt.scanned_at == datetime.fromtimestamp(1794859989, tz=UTC)
    r = pt.rows[0]
    assert r == {
        "item_id": 8170,
        "median": 1775,
        "min_buyout": 1599,
        "quantity": 5686,
        "median_7d": 1812,
        "median_30d": 1631,
        "low_30d": 500,
        "high_30d": 2143,
        "sales_per_day": 9136.8,
    }
    assert pt.rows[2]["min_buyout"] is None and pt.rows[2]["sales_per_day"] is None


def test_parse_pricetable_rejects_bad_header():
    with pytest.raises(ValueError):
        parse.parse_pricetable("XYZ|a|1|1\n1:2:3:4:5:6:7:8:9")


def test_rules():
    cfg = Config()
    assert rule_reason({"sales_per_day": 100, "quantity": 50, "median": 1}, cfg) == "bulk"
    assert rule_reason({"sales_per_day": 100, "quantity": 49, "median": 1}, cfg) is None
    # 20 sales/day x 10g median = 200 g/day -> valuable
    assert rule_reason({"sales_per_day": 20, "quantity": 1, "median": 100_000}, cfg) == "valuable"
    assert rule_reason({"sales_per_day": 19.9, "quantity": 1, "median": 10**7}, cfg) is None


def test_build_watchlist_order_quality_sticky_pinned():
    cfg = Config(pinned=(777,), scans_top_n=1)
    rows = [
        {"item_id": 1, "sales_per_day": 200, "quantity": 100, "median": 10, "min_buyout": 10},
        {"item_id": 2, "sales_per_day": 500, "quantity": 100, "median": 10, "min_buyout": 10},
        {"item_id": 3, "sales_per_day": 500, "quantity": 100, "median": 10, "min_buyout": 99},
        {"item_id": 4, "sales_per_day": 1, "quantity": 1, "median": 1, "min_buyout": 1},
    ]
    wl = build_watchlist(rows, cfg, qualities={3: "POOR"}, sticky_ids={4})
    assert [(e.item_id, e.reason) for e in wl] == [
        (2, "bulk"),
        (1, "bulk"),
        (4, "sticky"),
        (777, "pinned"),
    ]
    assert [e.scans for e in wl] == [True, False, False, False]


def test_series_rows():
    payload = {
        "series": [
            {
                "t": "2026-11-16T20:00:00.000Z",
                "min": 1,
                "median": 3,
                "p25": 2,
                "p75": 4,
                "quantity": 5,
                "auctions": 6,
            }
        ]
    }
    now = datetime(2026, 11, 16, 21, tzinfo=UTC)
    rows = parse.series_rows(payload, 42, "hour", now, "r1")
    assert rows[0]["hour"] == datetime(2026, 11, 16, 20, tzinfo=UTC)
    assert rows[0]["source"] == "api" and rows[0]["auctions"] == 6


def test_cutoff():
    cfg = Config()
    assert check_cutoff(cfg, date(2026, 11, 16)).allowed
    assert "WARNING" in check_cutoff(cfg, date(2026, 12, 1)).message
    assert check_cutoff(cfg, date(2026, 12, 9)).allowed
    assert not check_cutoff(cfg, date(2026, 12, 10)).allowed
    assert not check_cutoff(Config(api_archive_enabled=False), date(2026, 11, 16)).allowed


def test_load_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[collector]\napi_archive_until = "2026-12-01"\npinned = [1, 2]\n')
    cfg = load_config(p)
    assert cfg.api_archive_until == date(2026, 12, 1) and cfg.pinned == (1, 2)
    p.write_text("[collector]\nnope = 1\n")
    with pytest.raises(ValueError):
        load_config(p)


def test_env_overrides_archive_until(tmp_path, monkeypatch):
    p = tmp_path / "c.toml"
    p.write_text('[collector]\napi_archive_until = "2027-01-01"\n')
    monkeypatch.setenv("COPPERTRAIL_API_ARCHIVE_UNTIL", "2026-12-09")
    cfg = load_config(p)
    assert cfg.api_archive_until == date(2026, 12, 9)
    assert check_cutoff(cfg, date(2026, 12, 9)).allowed
    assert not check_cutoff(cfg, date(2026, 12, 10)).allowed
