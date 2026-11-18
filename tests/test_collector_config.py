import pytest

from coppertrail.collector.config import QUALITY_ORDER, load_config


def test_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.blizzard.house == 111 and cfg.blizzard.ruleset == 2
    assert cfg.blizzard.region == "eu" and cfg.blizzard.expect_house_name == "Alliance"
    assert cfg.selection.exclude_qualities == ("POOR",)
    assert cfg.selection.exclude_classes == ("Recipe",)
    assert cfg.selection.equipment_classes == ("Armor", "Weapon")
    assert cfg.selection.min_median == {"COMMON": 50}
    assert cfg.selection.equipment_min_quality == "EPIC"
    assert cfg.selection.include_unclassified is True
    assert (cfg.selection.max_items, cfg.selection.rank_days, cfg.selection.keep_rank) == (
        2000,
        7,
        2200,
    )
    assert cfg.retention.copied_days == 30 and cfg.retention.summary_retention_days == 0
    assert cfg.data_dir == tmp_path
    assert cfg.window_dir == tmp_path / "window"
    assert cfg.state_dir == tmp_path / ".state"


def test_toml_overrides(tmp_path):
    (tmp_path / "collector.toml").write_text(
        "[selection]\nmax_items = 500\nmin_median = { COMMON = 80 }\nexclude_classes = []\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.selection.max_items == 500
    assert cfg.selection.min_median == {"COMMON": 80}
    assert cfg.selection.exclude_classes == ()


def test_unknown_key_rejected(tmp_path):
    (tmp_path / "collector.toml").write_text("[selection]\nmax_itemz = 5\n")
    with pytest.raises(ValueError, match="max_itemz"):
        load_config(tmp_path)


def test_unknown_table_rejected(tmp_path):
    (tmp_path / "collector.toml").write_text("[collectr]\nx = 1\n")
    with pytest.raises(ValueError, match="collectr"):
        load_config(tmp_path)


def test_bad_quality_rejected(tmp_path):
    (tmp_path / "collector.toml").write_text('[selection]\nequipment_min_quality = "SHINY"\n')
    with pytest.raises(ValueError, match="SHINY"):
        load_config(tmp_path)


def test_quality_order():
    assert QUALITY_ORDER.index("POOR") < QUALITY_ORDER.index("COMMON") < QUALITY_ORDER.index("EPIC")
