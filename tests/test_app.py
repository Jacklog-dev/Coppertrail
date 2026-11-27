"""App shell: backend choice (never Qt), what JS can call, screenshots via headless Edge."""

from pathlib import Path

from coppertrail.ui.app import AppApi, gui_backend, js_facade, parse_size
from coppertrail.ui.bridge import Bridge
from coppertrail.ui.format import CREDIT_URL
from coppertrail.ui.screenshot import edge_command


def test_backend_never_qt():
    assert gui_backend("win32") == "edgechromium"
    assert gui_backend("linux") == "gtk"
    assert gui_backend("darwin") is None


def test_edge_command(tmp_path):
    out = tmp_path / "a.png"
    cmd = edge_command(Path("msedge.exe"), "http://127.0.0.1:1/", out, (1920, 1080))
    assert cmd[0] == "msedge.exe" and "--headless=new" in cmd
    assert "--window-size=1920,1080" in cmd and f"--screenshot={out}" in cmd


def test_parse_size():
    assert parse_size("1920x1080") == (1920, 1080)
    assert parse_size("1280X800") == (1280, 800)


def test_js_facade_has_only_exposed_methods(tmp_path):
    api = AppApi(tmp_path / "our.sqlite")
    facade = js_facade(api)
    assert {n for n in dir(facade) if not n.startswith("_")} == set(AppApi.EXPOSED)
    assert set(Bridge.EXPOSED) < set(AppApi.EXPOSED)
    assert facade.items() == {"at": None, "rows": []}


def test_open_credit_opens_credit_url(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    AppApi(tmp_path / "our.sqlite").open_credit()
    assert opened == [CREDIT_URL]


def test_default_database_is_in_the_config_folder(config_dir):
    assert Bridge().path == config_dir / "coppertrail.sqlite"
