import importlib.util
from pathlib import Path

import httpx
from blizzard_fixtures import mock_transport

from coppertrail.collector.blizzard import BlizzardClient
from coppertrail.collector.config import Blizzard
from coppertrail.ui import icons

ROOT = Path(__file__).resolve().parent.parent


def _script():
    spec = importlib.util.spec_from_file_location(
        "fetch_icon_map", ROOT / "scripts" / "fetch_icon_map.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def test_merge_keeps_old_and_ignores_none():
    merge = _script().merge
    assert merge({1: 10, 2: 20}, {2: None, 3: 30, 1: 11}) == {1: 11, 2: 20, 3: 30}


def test_write_then_read_round_trips(tmp_path):
    out = tmp_path / "data" / "icons.json"
    _script().write_map(out, {765: 134190, 2453: 134181})
    assert icons.read_map(out) == {765: 134190, 2453: 134181}


def test_media_icon_reads_file_data_id():
    def media(req):
        if req.url.params["namespace"].startswith("static-forever"):
            body = {"assets": [{"key": "icon", "value": "x", "file_data_id": 134181}]}
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    def missing(req):
        return httpx.Response(404)

    routes = {"/data/wow/media/item/2453": media, "/data/wow/media/item/9": missing}
    with BlizzardClient(
        Blizzard(rate_per_s=1e9),
        "id",
        "secret",
        transport=mock_transport(routes),
        sleep=lambda s: None,
    ) as c:
        assert c.media_icon(2453) == 134181
        assert c.media_icon(9) is None


def test_shipped_map_is_valid():
    path = icons.map_path()
    if path.exists():
        m = icons.read_map(path)
        assert m and all(k > 0 and v > 0 for k, v in m.items())
