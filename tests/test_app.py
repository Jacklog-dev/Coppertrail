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


def test_pull_always_reports_even_if_reload_fails(monkeypatch, archive, config_dir):
    # final review, Important 2: a failing state() must not leave the UI at "Pulling…"
    from coppertrail.ui.pull import PullResult

    monkeypatch.setattr(
        "coppertrail.ui.app.run_pull", lambda d: PullResult(True, "Pulled latest data", "")
    )
    events = []
    api = AppApi(archive, emit=lambda event, payload: events.append((event, payload)))

    def boom():
        raise RuntimeError("schema changed")

    monkeypatch.setattr(api, "state", boom)
    api.pull_latest()
    api.wait_for_pull(timeout=10)
    (event, payload), *_ = events
    assert event == "pull" and payload["ok"] is False
    assert "schema changed" in payload["detail"]
    assert payload["failure"]["title"] == "Pull failed"


def test_pull_reload_waits_for_the_bridge_lock(monkeypatch, archive, config_dir):
    # final review, Important 3: the worker reloads under the same lock as JS calls
    from coppertrail.ui.pull import PullResult

    monkeypatch.setattr(
        "coppertrail.ui.app.run_pull", lambda d: PullResult(True, "Pulled latest data", "")
    )
    events = []
    api = AppApi(archive, emit=lambda event, payload: events.append((event, payload)))
    with api.lock:
        api.pull_latest()
        api.wait_for_pull(timeout=0.3)
        assert events == []
    api.wait_for_pull(timeout=10)
    assert events and events[0][1]["ok"] is True


def test_pull_skips_reload_when_folder_changed(monkeypatch, archive, tmp_path, config_dir):
    from coppertrail.ui.pull import PullResult

    api = AppApi(archive, emit=lambda event, payload: events.append((event, payload)))
    other = tmp_path / "other"
    other.mkdir()

    def pull(d):
        api.data_dir = other  # the user picked another folder while git ran
        return PullResult(True, "Pulled latest data", "")

    monkeypatch.setattr("coppertrail.ui.app.run_pull", pull)
    events = []
    loads = []
    monkeypatch.setattr(api, "_load", lambda: loads.append(1))
    api.pull_latest()
    api.wait_for_pull(timeout=10)
    assert loads == []
    assert events[0][1]["ok"] is False
    assert events[0][1]["message"] == "Pull finished, but the data folder changed meanwhile"


def test_js_facade_uses_the_bridge_lock(archive, config_dir):
    import threading

    api = AppApi(archive, emit=lambda *a: None)
    facade = js_facade(api)
    done = threading.Event()
    with api.lock:
        t = threading.Thread(target=lambda: (facade.state(), done.set()))
        t.start()
        assert not done.wait(0.3)
    assert done.wait(10)


def test_failed_pull_event_carries_failure_state(monkeypatch, archive, config_dir):
    from coppertrail.ui.pull import FAILED, PullResult

    monkeypatch.setattr(
        "coppertrail.ui.app.run_pull",
        lambda d: PullResult(False, FAILED, "fatal: could not read from remote", 128),
    )
    events = []
    api = AppApi(archive, emit=lambda event, payload: events.append((event, payload)))
    api.pull_latest()
    api.wait_for_pull(timeout=10)
    (event, payload), *_ = events
    assert payload["failure"]["cause"] == "git stopped: could not read from remote."
    assert "exit 128" in payload["failure"]["request"]
    assert payload["state"]["status"]["empty"] is False


def test_view_flag_opens_that_view(monkeypatch, archive, config_dir):
    from coppertrail.ui import app

    pages = []
    monkeypatch.setattr(app, "run_screenshot", lambda bridge, page, out, size: pages.append(page))
    monkeypatch.setattr(app, "run_window", lambda api, page, size: pages.append(page))
    app.main(["--data-dir", str(archive), "--screenshot", "x.png", "--view", "item"])
    app.main(["--data-dir", str(archive), "--view", "item"])
    assert pages == ["index.html#item", "index.html"]  # the window takes a file path


def test_tab_flag_and_warm(monkeypatch, archive, config_dir):
    from coppertrail.ui import app

    pages = []
    monkeypatch.setattr(app, "run_screenshot", lambda bridge, page, out, size: pages.append(page))
    for view, tab in (("patterns", "mispricings"), ("movers", "24h"), ("item", "x")):
        app.main(
            ["--data-dir", str(archive), "--screenshot", "x.png", "--view", view, "--tab", tab]
        )
    assert pages == ["index.html#patterns/mispricings", "index.html#movers/24h", "index.html#item"]

    calls = []

    class Fake:
        def __getattr__(self, name):
            def f(*args):
                calls.append((name, args))
                if name == "overview":
                    raise RuntimeError("left to the page")
                return {"rows": [{"id": 7}]} if name == "item_list" else {}

            return f

    for page in ("index.html", "index.html#item", "index.html#patterns/daily_rhythm",
                 "index.html#movers/30d"):  # fmt: skip
        app.warm(Fake(), page)
    assert calls == [
        ("overview", ()), ("overview_events", ()),
        ("item_list", ()), ("item_detail", (7,)),
        ("patterns", ("daily_rhythm",)),
        ("movers", ("30d",)), ("mispricings_now", ()),
    ]  # fmt: skip
