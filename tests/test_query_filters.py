from datetime import UTC, date, datetime, timedelta

from coppertrail.query.catalog import ArchiveStatus, archive_status, load_items
from coppertrail.query.filtering import apply_filters, date_window, item_classes
from coppertrail.query.groups import ItemGroup, load_groups, save_groups, starter_groups
from coppertrail.query.settings import Filters, Settings, load_settings, save_settings
from tests.new_archive import make_archive


def test_catalog_uses_latest_hour(archive):
    items = {i.name: i for i in load_items(archive)}
    assert len(items) == 9
    assert items["Rugged Leather"].min_buyout == 1_495
    assert items["Light Leather"].min_buyout == 35  # the newest hour, not the older 30
    assert items["Rugged Leather"].sales_per_day == 9_221.0
    assert items["Accurate Scope"].item_class == "Consumable"


def test_archive_status(archive):
    st = archive_status(archive, now=datetime(2026, 11, 16, 9, 0, tzinfo=UTC))
    assert st.as_of == datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
    assert st.first_hour == datetime(2026, 11, 9, tzinfo=UTC)
    assert st.last_hour == datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
    assert st.hours == 176 and st.missing_hours_7d == 0 and not st.stale
    assert (st.first_day, st.last_day, st.days) == (date(2026, 11, 9), date(2026, 11, 16), 8)
    assert st.age_days(datetime(2026, 11, 19, 7, 0, tzinfo=UTC)) == 3.0
    assert archive_status(archive, now=datetime(2026, 11, 16, 10, 1, tzinfo=UTC)).stale


def test_archive_status_counts_missing_hours(tmp_path):
    t0 = datetime(2026, 11, 10, tzinfo=UTC)
    rows = [{"hour": t0 + timedelta(hours=h), "min": 5} for h in range(10 * 24) if h % 50]
    later = datetime(2026, 11, 25, tzinfo=UTC)
    st = archive_status(make_archive(tmp_path, [(1, "X", "Y")], {1: rows}), now=later)
    assert st.hours == 10 * 24 - 5 and st.first_hour == t0 + timedelta(hours=1)
    assert st.missing_hours_7d == 3  # hours 100, 150 and 200; 0 and 50 are outside 7 d
    assert st.as_of == t0 + timedelta(hours=239, minutes=22)
    assert st.stale


def test_empty_data_folder(tmp_path):
    assert load_items(tmp_path) == []
    st = archive_status(tmp_path)
    assert st.empty and st.days == 0


def test_starter_groups_match_by_name(archive):
    items = load_items(archive)
    groups = {g.name: {i.name for i in g.members(items)} for g in starter_groups()}
    assert groups["Leather chain"] == {
        "Light Leather",
        "Rugged Leather",
        "Cured Rugged Hide",
        "Rugged Armor Kit",
    }
    assert groups["Herbs"] == {"Peacebloom", "Black Lotus"}
    assert groups["Ore and bars"] == {"Thorium Bar"}
    assert "Black Lotus" in groups["Scarce goods"]


def test_group_add_remove_overrides_patterns(archive):
    items = load_items(archive)
    g = ItemGroup("Leather", patterns=["* Leather"])
    g.remove(2318)  # Light Leather, matched by the pattern
    assert "Light Leather" not in {i.name for i in g.members(items)}
    g.add(2318)
    g.add(3928)
    assert {i.name for i in g.members(items)} == {
        "Light Leather",
        "Rugged Leather",
        "Superior Healing Potion",
    }


def test_groups_round_trip_and_fallback(config_dir):
    assert [g.name for g in load_groups()] == [g.name for g in starter_groups()]
    save_groups([ItemGroup("Mine", item_ids=[1, 2], patterns=["X *"], excluded_ids=[3])])
    assert load_groups() == [ItemGroup("Mine", [1, 2], ["X *"], [3])]
    (config_dir / "groups.json").write_text("{broken", encoding="utf-8")
    assert len(load_groups()) == len(starter_groups())


def test_filters_combine(archive):
    items = load_items(archive)
    groups = starter_groups()
    names = lambda f: {i.name for i in apply_filters(items, groups, f)}  # noqa: E731
    assert len(names(Filters())) == 9
    assert names(Filters(groups=["Herbs", "Ore and bars"])) == {
        "Peacebloom",
        "Black Lotus",
        "Thorium Bar",
    }
    assert names(Filters(groups=["Leather chain"], min_sales=50)) == {
        "Light Leather",
        "Rugged Leather",
    }
    assert names(Filters(item_class="Consumable")) == {"Superior Healing Potion", "Accurate Scope"}
    assert names(Filters(search="  rugged ")) == {
        "Rugged Leather",
        "Cured Rugged Hide",
        "Rugged Armor Kit",
    }
    assert names(Filters(groups=["Deleted group"])) == names(Filters())
    assert item_classes(items) == ["Trade Goods", "Consumable"]


def test_active_filters():
    assert Filters().active() == []
    f = Filters(groups=["Herbs"], search=" x ", range="7d", min_sales=50, item_class="Armor")
    assert f.active() == ["Groups", "Class", "Search", "Date range", "Min sales/day"]
    assert Filters(search="   ").active() == []


def test_date_window_clamps_to_archive():
    st = ArchiveStatus(datetime(2026, 11, 9, tzinfo=UTC), datetime(2026, 11, 16, tzinfo=UTC))
    assert date_window(Filters(), st) == (date(2026, 11, 9), date(2026, 11, 16))  # 30 d
    assert date_window(Filters(range="7d"), st) == (date(2026, 11, 10), date(2026, 11, 16))
    assert date_window(Filters(range="24h"), st) == (date(2026, 11, 16), date(2026, 11, 16))
    custom = Filters(range="custom", date_from=date(2026, 11, 20), date_to=date(2026, 10, 1))
    assert date_window(custom, st) == (date(2026, 11, 9), date(2026, 11, 16))
    empty = ArchiveStatus(None, None)
    assert date_window(Filters(range="7d"), empty, today=date(2026, 11, 17)) == (
        date(2026, 11, 11),
        date(2026, 11, 17),
    )


def test_settings_round_trip(config_dir):
    assert load_settings() == Settings()
    s = Settings(
        data_dir="D:/data",
        filters=Filters(
            groups=["Herbs"],
            range="custom",
            date_from=date(2026, 11, 10),
            date_to=date(2026, 11, 12),
            min_sales=50,
        ),
    )
    save_settings(s)
    assert load_settings() == s


def test_settings_sanitise_bad_values(config_dir):
    config_dir.mkdir(parents=True)
    (config_dir / "settings.json").write_text(
        '{"filters": {"range": "custom", "min_sales": -5, "unknown": 1}}', encoding="utf-8"
    )
    f = load_settings().filters
    assert f.range == "30d"  # custom without dates falls back
    assert f.min_sales == 0
