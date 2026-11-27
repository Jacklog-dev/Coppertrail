from pathlib import Path

from coppertrail.ui import icons

ROOT = Path(__file__).resolve().parent.parent


def test_icon_url_builds_render_url():
    url = icons.icon_url(2453, {2453: 134181})
    assert url == "https://render.worldofwarcraft.com/eu/icons/56/134181.jpg"


def test_icon_url_none_without_entry():
    assert icons.icon_url(1, {2453: 134181}) is None


def test_read_map_missing_or_bad_file_is_empty(tmp_path):
    assert icons.read_map(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2", encoding="utf-8")
    assert icons.read_map(bad) == {}
    bad.write_text("[1, 2]", encoding="utf-8")
    assert icons.read_map(bad) == {}
    bad.write_text('{"x": 3}', encoding="utf-8")
    assert icons.read_map(bad) == {}


def test_shipped_map_is_valid():
    path = icons.map_path()
    if path.exists():
        m = icons.read_map(path)
        assert m and all(k > 0 and v > 0 for k, v in m.items())
