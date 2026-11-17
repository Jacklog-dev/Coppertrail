"""App shell: backend choice (never Qt), what JS can call, screenshots via headless Edge."""

from pathlib import Path

from coppertrail.ui.app import AppApi, gui_backend, js_facade, parse_size
from coppertrail.ui.bridge import Bridge
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
    assert cmd[-1] == "http://127.0.0.1:1/"


def test_parse_size():
    assert parse_size("1920x1080") == (1920, 1080)
    assert parse_size("1280X800") == (1280, 800)


def test_app_api_exposes_extra_methods():
    assert {"pick_data_folder", "open_credit"} <= set(AppApi.EXPOSED)
    assert set(Bridge.EXPOSED) <= set(AppApi.EXPOSED)


def test_js_facade_has_only_exposed_methods(archive, config_dir):
    api = AppApi(archive)
    facade = js_facade(api)
    public = {n for n in dir(facade) if not n.startswith("_")}
    assert public == set(AppApi.EXPOSED)
    assert facade.state()["items"]["total"] == 9


def test_open_credit_only_opens_ahledger(monkeypatch, archive, config_dir):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    AppApi(archive).open_credit()
    assert opened == ["https://ahledger.com"]


def test_pull_runs_in_background_and_emits(archive, config_dir):
    events = []
    api = AppApi(archive, emit=lambda event, payload: events.append((event, payload)))
    assert api.pull_latest() == {"started": True}
    api.wait_for_pull(timeout=10)
    (event, payload), *_ = events
    assert event == "pull" and payload["ok"] is False
    assert payload["message"] == "The data folder is not a git clone"
    assert payload["state"]["items"]["total"] == 9
