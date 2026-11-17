"""The dev/screenshot server: 127.0.0.1 only, web/ only, listed bridge methods only."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from coppertrail.ui.bridge import Bridge
from coppertrail.ui.devserver import serve


def post(url, payload):
    req = Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


@pytest.fixture
def server(archive, config_dir):
    srv, url = serve(Bridge(archive))
    yield url
    srv.shutdown()
    srv.server_close()


def test_binds_localhost_only(archive, config_dir):
    srv, url = serve(Bridge(archive))
    try:
        assert url.startswith("http://127.0.0.1:") and url.endswith("/")
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.shutdown()
        srv.server_close()


def test_serves_static_files(server):
    with urlopen(server + "js/api.js", timeout=5) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/javascript")
    with urlopen(server + "css/tokens.css", timeout=5) as resp:
        assert resp.headers["Content-Type"].startswith("text/css")


def test_calls_bridge(server):
    body = post(server + "api/state", {"args": []})
    assert body["result"]["items"]["total"] == 9
    body = post(server + "api/set_filters", {"args": [{"min_sales": 50}]})
    assert body["result"]["activeLabel"] == "1 filter active"
    body = post(server + "api/match_names", {"args": [["Black Lotus"]]})
    assert body["result"]["ids"] == [13468]


def test_bridge_errors_are_500(server):
    with pytest.raises(HTTPError) as err:
        post(server + "api/set_filters", {"args": ["not a dict"]})
    assert err.value.code == 500
    assert "error" in json.loads(err.value.read().decode("utf-8"))


@pytest.mark.parametrize(
    "path",
    ["../pyproject.toml", "..%2F..%2Fpyproject.toml", "%2e%2e/bridge.py", "..\\bridge.py"],
)
def test_no_files_outside_web(server, path):  # Review Focus 4
    with pytest.raises(HTTPError) as err:
        urlopen(server + path, timeout=5)
    assert err.value.code == 404


@pytest.mark.parametrize("name", ["_load", "__init__", "EXPOSED", "nope", "state/../x"])
def test_only_exposed_methods(server, name):  # Review Focus 4
    with pytest.raises(HTTPError) as err:
        post(server + "api/" + name, {"args": []})
    assert err.value.code == 404


def test_missing_file_is_404(server):
    with pytest.raises(HTTPError) as err:
        urlopen(server + "missing.html", timeout=5)
    assert err.value.code == 404


def test_dev_marker(server):
    # api.js asks this to tell the dev server from pywebview's own file server.
    with urlopen(server + "api", timeout=5) as resp:
        assert json.loads(resp.read().decode("utf-8")) == {"dev": True}
