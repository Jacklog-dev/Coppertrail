"""Item details on the Pi (pi/coppertrail_raw.py `items`). Hand-made fixtures, no network."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sqlite3
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "coppertrail_raw", Path(__file__).parents[1] / "pi" / "coppertrail_raw.py"
)
raw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(raw)

NOW = datetime(2026, 11, 24, 13, 0, 5, tzinfo=UTC)
LM = datetime(2026, 11, 24, 12, 22, 55, tzinfo=UTC)
SECRET = "s3cr3t-value"
TOKEN = "tok-abc"
ITEMS = {
    "auctions": [
        {"id": 1, "item": {"id": 2589}, "quantity": 20, "buyout": 4000, "time_left": "LONG"},
        {"id": 2, "item": {"id": 7909, "rand": 5}, "quantity": 1, "bid": 900, "time_left": "SHORT"},
    ]
}
COMMODITIES = {
    "auctions": [
        {"id": 10, "item": {"id": 2592}, "quantity": 200, "unit_price": 55, "time_left": "LONG"}
    ]
}
DETAIL = {"id": 2589, "name": "Made-up Cloth", "sell_price": 13}


def db(tmp_path: Path) -> Path:
    return tmp_path / "raw.sqlite"


def rows(path: Path, sql: str) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj).encode())


class TokenOnly:
    """Opener for raw.Client that only answers the token request."""

    def __init__(self):
        self.calls = 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        body = json.dumps({"access_token": TOKEN}).encode()

        class R:
            def read(self):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return R()


class Answer:
    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None):
        self.status = status
        self._body = body
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)

    def read(self):
        return self._body


class FakeConn:
    """http.client-style connection. `script` maps (namespace, item_id) to a list of answers;
    an unscripted lookup answers 404."""

    def __init__(self, script: dict, clock: list | None = None):
        self.script = script
        self.clock = clock
        self.requests: list[tuple[str, dict]] = []
        self._next: Answer | None = None

    def request(self, method, url, headers=None):
        self.requests.append((url, headers or {}))
        if self.clock is not None:
            self.clock[0] += timedelta(minutes=1)
        parts = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qs(parts.query)
        item_id = int(parts.path.rsplit("/", 1)[1])
        answers = self.script.get((q["namespace"][0], item_id))
        self._next = answers.pop(0) if answers else Answer(404)

    def getresponse(self):
        return self._next

    def close(self):
        pass


def item_client(conn: FakeConn, made: list | None = None):
    client = raw.Client("id", SECRET, opener=TokenOnly(), sleep=lambda s: None)

    def connect():
        if made is not None:
            made.append(1)
        return conn

    return raw.ItemClient(client, connect=connect, sleep=lambda s: None)


def ok(obj=DETAIL) -> Answer:
    return Answer(200, gz(obj), {"Content-Encoding": "gzip"})


def seed_listings(tmp_path):
    con = raw.connect(db(tmp_path))
    raw.store_snapshot(con, "items", LM, "ns", gz(ITEMS), "gzip", NOW)
    raw.store_snapshot(
        con, "commodities", LM, "ns", json.dumps(COMMODITIES).encode(), "identity", NOW
    )
    con.close()


def test_item_ids_from_gzip_body():
    assert raw.item_ids(gz(ITEMS), "gzip") == {2589, 7909}


def test_item_ids_from_identity_body():
    assert raw.item_ids(json.dumps(ITEMS).encode(), "identity") == {2589, 7909}


def test_listed_ids_reads_newest_snapshot_of_each_endpoint(tmp_path):
    seed_listings(tmp_path)
    con = raw.connect(db(tmp_path))
    assert raw.listed_ids(con) == {2589, 7909, 2592}
    con.close()


def test_due_items_order(tmp_path):
    con = raw.connect(db(tmp_path))
    raw.store_item(con, 2, "static-forever-eu", 200, b"{}", "identity", NOW - timedelta(days=26))
    raw.store_item(con, 3, "static-forever-eu", 200, b"{}", "identity", NOW - timedelta(days=10))
    raw.store_item(con, 4, None, 404, None, None, NOW - timedelta(days=8))
    raw.store_item(con, 5, None, 404, None, None, NOW - timedelta(days=2))
    assert raw.due_items(con, {1, 2, 3, 4, 5}, NOW) == [1, 2, 4]
    con.close()


def test_due_items_uses_newest_row(tmp_path):
    con = raw.connect(db(tmp_path))
    raw.store_item(con, 2, "static-forever-eu", 200, b"{}", "identity", NOW - timedelta(days=28))
    raw.store_item(con, 2, "static-forever-eu", 200, b"{}", "identity", NOW - timedelta(days=1))
    assert raw.due_items(con, {2}, NOW) == []
    con.close()


def test_lookup_sends_token_and_gzip():
    conn = FakeConn({("static-forever-eu", 2589): [ok()]})
    assert item_client(conn).lookup(2589) == (200, "static-forever-eu", gz(DETAIL), "gzip")
    url, headers = conn.requests[0]
    assert url.startswith("/data/wow/item/2589?")
    assert "locale=en_GB" in url
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Accept-Encoding"] == "gzip"


def test_lookup_falls_back_to_classic():
    conn = FakeConn({("static-classic1x-eu", 2589): [Answer(200, b"{}")]})
    assert item_client(conn).lookup(2589) == (200, "static-classic1x-eu", b"{}", "identity")


def test_lookup_retries_on_429():
    conn = FakeConn({("static-forever-eu", 1): [Answer(429, headers={"Retry-After": "1"}), ok()]})
    assert item_client(conn).lookup(1)[0] == 200


def test_lookup_refreshes_token_on_401():
    conn = FakeConn({("static-forever-eu", 1): [Answer(401), ok()]})
    assert item_client(conn).lookup(1)[0] == 200


def test_lookup_reconnects_once_after_dropped_connection():
    conn = FakeConn({("static-forever-eu", 1): [ok()]})
    real_request = conn.request
    dropped = []

    def flaky(method, url, headers=None):
        if not dropped:
            dropped.append(1)
            raise ConnectionResetError
        real_request(method, url, headers)

    conn.request = flaky
    made = []
    assert item_client(conn, made).lookup(1)[0] == 200
    assert len(made) == 2


def test_lookups_reuse_one_connection():
    conn = FakeConn({("static-forever-eu", i): [ok()] for i in (1, 2, 3)})
    made = []
    ic = item_client(conn, made)
    for i in (1, 2, 3):
        ic.lookup(i)
    assert len(made) == 1


def test_lookup_found_nowhere_stores_one_404(tmp_path):
    seed_listings(tmp_path)
    conn = FakeConn({})
    assert raw.run_items(item_client(conn), db(tmp_path), now=lambda: NOW)
    got = rows(db(tmp_path), "SELECT item_id, namespace, status, body FROM item ORDER BY item_id")
    assert got == [(2589, None, 404, None), (2592, None, 404, None), (7909, None, 404, None)]
    assert len(conn.requests) == 6  # forever, then classic, for each


def test_run_stores_found_items(tmp_path):
    seed_listings(tmp_path)
    conn = FakeConn({("static-forever-eu", 2589): [ok()]})
    raw.run_items(item_client(conn), db(tmp_path), now=lambda: NOW)
    assert rows(
        db(tmp_path), "SELECT namespace, status, encoding, body FROM item WHERE item_id = 2589"
    ) == [("static-forever-eu", 200, "gzip", gz(DETAIL))]


def test_run_stops_at_deadline_and_keeps_what_it_got(tmp_path, capsys):
    seed_listings(tmp_path)
    clock = [datetime(2026, 11, 24, 13, 18, tzinfo=UTC)]
    conn = FakeConn({("static-forever-eu", i): [ok()] for i in (2589, 2592, 7909)}, clock)
    assert raw.run_items(item_client(conn), db(tmp_path), now=lambda: clock[0])
    assert rows(db(tmp_path), "SELECT count(*) FROM item") == [(2,)]
    assert "items: 2 looked up (2 found, 0 not found), 1 left" in capsys.readouterr().out


def test_items_with_no_snapshot_does_nothing(tmp_path):
    conn = FakeConn({})
    assert raw.run_items(item_client(conn), db(tmp_path), now=lambda: NOW)
    assert conn.requests == []


def test_failed_lookup_ends_run_with_false(tmp_path, capsys):
    seed_listings(tmp_path)
    conn = FakeConn({("static-forever-eu", 2589): [Answer(403)]})
    assert raw.run_items(item_client(conn), db(tmp_path), now=lambda: NOW) is False
    assert "item 2589: failed (403)" in capsys.readouterr().out


def test_item_log_has_no_secret_or_body(tmp_path, capsys):
    seed_listings(tmp_path)
    conn = FakeConn({("static-forever-eu", 2589): [ok()]})
    raw.run_items(item_client(conn), db(tmp_path), now=lambda: NOW)
    out = capsys.readouterr().out
    for text in (SECRET, TOKEN, "Made-up Cloth"):
        assert text not in out
