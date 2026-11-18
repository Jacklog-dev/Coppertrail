"""The Qt-free bridge the web front end talks to (HANDOVER 8a/8b filter bar and status strip)."""

from datetime import UTC, datetime

from coppertrail.query.groups import load_groups
from coppertrail.query.settings import Filters, load_settings
from coppertrail.ui.bridge import Bridge
from coppertrail.ui.format import CREDIT_TEXT, CREDIT_URL


def _keys(d):
    if isinstance(d, dict):
        for k, v in d.items():
            yield k
            yield from _keys(v)
    elif isinstance(d, list):
        for v in d:
            yield from _keys(v)


def NOW():  # noqa: N802
    return datetime(2026, 11, 16, 9, tzinfo=UTC)


def test_state_loads_archive(archive, config_dir):
    s = Bridge(archive, now=NOW).state()
    assert s["items"]["sub"] == "9 of 9 items"
    assert s["items"]["shown"] == 9 and s["items"]["total"] == 9
    assert s["activeLabel"] == "No filters" and s["active"] == []
    assert s["window"]["label"] == "9 Nov – 16 Nov 2026"
    assert s["window"]["archiveFrom"] == "2026-11-09"
    assert s["status"]["text"] == "Data as of 16 Nov 2026, 08:00"
    assert not s["status"]["stale"] and not s["status"]["empty"]
    assert s["status"]["canPull"] is False
    assert s["status"]["pullHint"] == "The data folder is not a git clone"
    assert s["creditText"] == CREDIT_TEXT and s["creditUrl"] == CREDIT_URL
    assert not [k for k in _keys(s) if "cutoff" in k.lower()]
    assert s["classes"] == ["Trade Goods", "Consumable"]
    row = next(r for r in s["items"]["rows"] if r["name"] == "Rugged Leather")
    assert row == {
        "id": 8170,
        "name": "Rugged Leather",
        "class": "Trade Goods",
        "price": {"parts": [[14, "s"], [95, "c"]], "text": "14s 95c"},
        "salesPerDay": "9,221",
    }


def test_filters_apply_and_persist(archive, config_dir):
    b = Bridge(archive, now=NOW)
    s = b.set_filters({"groups": ["Leather chain"], "min_sales": 50})
    assert s["items"]["sub"] == "2 of 9 items"
    assert s["activeLabel"] == "2 filters active"
    assert s["active"] == ["Groups", "Min sales/day"]
    assert load_settings().filters.groups == ["Leather chain"]
    assert b.set_filters({"search": "rugged"})["activeLabel"] == "3 filters active"
    assert b.reset_filters()["items"]["sub"] == "9 of 9 items"
    assert load_settings().filters == Filters()


def test_one_filter_label(archive, config_dir):
    s = Bridge(archive, now=NOW).set_filters({"item_class": "Consumable"})
    assert s["activeLabel"] == "1 filter active" and s["items"]["sub"] == "2 of 9 items"


def test_saved_filters_load_on_start(archive, config_dir):
    Bridge(archive, now=NOW).set_filters({"min_sales": 50})
    assert Bridge(archive, now=NOW).state()["filters"]["min_sales"] == 50


def test_data_dir_override_not_saved(archive, config_dir):
    Bridge(archive, now=NOW).set_filters({"min_sales": 10})
    assert load_settings().data_dir == ""


def test_set_data_dir_is_saved(archive, config_dir):
    b = Bridge(now=NOW)
    s = b.set_data_dir(str(archive))
    assert load_settings().data_dir == str(archive)
    assert s["dataDir"] == str(archive) and s["items"]["total"] == 9


def test_popover_counts(archive, config_dir):
    s = Bridge(archive, now=NOW).set_filters(
        {"groups": ["Leather chain", "Herbs"], "min_sales": 50}
    )
    assert s["groupsSummary"] == "2 of 6 selected · 6 items"
    assert s["minSalesPass"] == "3 of 9 items pass"
    assert s["groupsLabel"] == "Leather chain, Herbs"


def test_popover_counts_without_selection(archive, config_dir):
    s = Bridge(archive, now=NOW).state()
    assert s["groupsSummary"] == "0 of 6 selected · 9 items"
    assert s["groupsLabel"] == "All groups"
    assert s["minSalesPass"] == "9 of 9 items pass"
    leather = next(g for g in s["groups"] if g["name"] == "Leather chain")
    assert leather["count"] == 4 and leather["patterns"]


def test_custom_range_any_order(archive, config_dir):
    s = Bridge(archive, now=NOW).set_filters(
        {"range": "custom", "date_from": "2026-11-12", "date_to": "2026-11-10"}
    )
    assert s["window"]["label"] == "10 Nov – 12 Nov 2026"
    assert s["active"] == ["Date range"]


def test_stale_archive(archive, config_dir):  # Review Focus 1
    s = Bridge(archive, now=lambda: datetime(2026, 11, 19, 9, tzinfo=UTC)).state()
    assert s["status"]["stale"]
    assert s["status"]["text"] == "Data is 3 days old · as of 16 Nov 2026, 08:00"


def test_empty_folder(tmp_path, config_dir):  # Review Focus 2
    s = Bridge(tmp_path / "nothing", now=NOW).state()
    assert s["status"]["empty"] and s["status"]["text"] == "No data yet"
    assert not s["status"]["stale"]
    assert s["items"]["total"] == 0 and s["items"]["sub"] == "0 of 0 items"
    assert s["status"]["canPull"] is False


def test_group_rename_and_delete_follow_selection(archive, config_dir):  # Review Focus 5
    b = Bridge(archive, now=NOW)
    b.set_filters({"groups": ["Herbs", "Cloth"]})
    groups = [g for g in b.state()["groups"] if g["name"] != "Cloth"]
    for g in groups:
        if g["name"] == "Herbs":
            g["name"] = "Flowers"
    s = b.save_groups(groups, renamed={"Herbs": "Flowers"})
    assert s["filters"]["groups"] == ["Flowers"]
    assert load_settings().filters.groups == ["Flowers"]
    assert [g.name for g in load_groups()] == [g["name"] for g in groups]


def test_group_editor_helpers(archive, config_dir):
    b = Bridge(archive, now=NOW)
    leather = next(g for g in b.state()["groups"] if g["name"] == "Leather chain")
    assert [r["name"] for r in b.group_members(leather)] == [
        "Cured Rugged Hide",
        "Light Leather",
        "Rugged Armor Kit",
        "Rugged Leather",
    ]
    found = b.search_items("potion", leather)
    assert [r["name"] for r in found["rows"]] == ["Superior Healing Potion"]
    assert found["note"] == "1 result not yet in group"
    assert b.search_items("leather", leather)["note"] == "0 results not yet in group"
    m = b.match_names(["Peacebloom", "No Such Item", "black lotus"])
    assert sorted(m["ids"]) == [2447, 13468] and m["missing"] == 1
    assert m["note"] == "1 pasted name not found"
    assert b.match_names(["Peacebloom"])["note"] == ""


def test_pull_on_non_clone_reports(archive, config_dir):
    r = Bridge(archive, now=NOW).pull_latest()
    assert {k: r[k] for k in ("ok", "message", "detail", "returncode")} == {
        "ok": False,
        "message": "The data folder is not a git clone",
        "detail": "",
        "returncode": None,
    }
    assert r["failure"]["title"] == "Pull failed"


def test_exposed_methods_exist():
    for name in Bridge.EXPOSED:
        assert callable(getattr(Bridge, name)) and not name.startswith("_")


def _corrupt_folder(tmp_path):
    bad = tmp_path / "bad"
    (bad / "window" / "items").mkdir(parents=True)
    (bad / "window" / "items" / "2026-11-16.parquet").write_bytes(b"not a parquet file")
    return bad


def test_unreadable_folder_does_not_raise(tmp_path, config_dir):  # final review, Important 1
    bridge = Bridge(_corrupt_folder(tmp_path))
    st = bridge.state()
    assert st["items"]["total"] == 0
    assert st["status"]["text"].startswith("Could not read this data folder")
    assert st["status"]["error"] is True


def test_choosing_unreadable_folder_keeps_app_startable(archive, tmp_path, config_dir):
    bridge = Bridge()
    st = bridge.set_data_dir(str(_corrupt_folder(tmp_path)))
    assert st["status"]["error"] is True
    Bridge()  # the next start reads the saved (bad) folder and must still open
    assert Bridge(archive).state()["status"]["error"] is False
