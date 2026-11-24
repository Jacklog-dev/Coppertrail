"""The Pi's raw listings store (pi/coppertrail_raw.py). Hand-made fixtures, no network."""

from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sqlite3
import urllib.error
from datetime import UTC, datetime
from email.message import Message
from email.utils import format_datetime
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "coppertrail_raw", Path(__file__).parents[1] / "pi" / "coppertrail_raw.py"
)
raw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(raw)

LM = datetime(2026, 11, 24, 12, 22, 55, tzinfo=UTC)
FETCHED = datetime(2026, 11, 24, 12, 27, 3, tzinfo=UTC)
ITEMS = {
    "auctions": [
        {
            "id": 1,
            "item": {"id": 2589},
            "quantity": 20,
            "buyout": 4000,
            "bid": 3000,
            "time_left": "LONG",
        },
        {
            "id": 2,
            "item": {"id": 7909, "rand": 5},
            "quantity": 1,
            "bid": 900,
            "time_left": "SHORT",
            "new_field": "x",
        },
    ]
}
COMMODITIES = {
    "auctions": [
        {
            "id": 10,
            "item": {"id": 2592},
            "quantity": 200,
            "unit_price": 55,
            "time_left": "VERY_LONG",
        },
    ]
}
SECRET = "s3cr3t-value"
TOKEN = "tok-abc"


def rows(path: Path, sql: str) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# Store -----------------------------------------------------------------------


def gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj).encode())


def db(tmp_path: Path) -> Path:
    return tmp_path / "raw.sqlite"


def test_store_keeps_body_as_received(tmp_path):
    body = gz(ITEMS)
    con = raw.connect(db(tmp_path))
    sid = raw.store_snapshot(con, "items", LM, "dynamic-forever-eu", body, "gzip", FETCHED)
    con.close()
    assert sid == 1
    assert rows(
        db(tmp_path),
        "SELECT endpoint, last_modified, fetched_at, namespace, encoding, size, body FROM snapshot",
    ) == [
        (
            "items",
            "2026-11-24T12:22:55Z",
            "2026-11-24T12:27:03Z",
            "dynamic-forever-eu",
            "gzip",
            len(body),
            body,
        )
    ]


def test_store_twice_writes_once(tmp_path):
    con = raw.connect(db(tmp_path))
    raw.store_snapshot(con, "items", LM, "ns", gz(ITEMS), "gzip", FETCHED)
    assert raw.store_snapshot(con, "items", LM, "ns", gz(ITEMS), "gzip", FETCHED) is None
    con.close()
    assert rows(db(tmp_path), "SELECT count(*) FROM snapshot") == [(1,)]


def test_broken_gzip_is_refused(tmp_path):
    con = raw.connect(db(tmp_path))
    with pytest.raises(ValueError):
        raw.store_snapshot(con, "items", LM, "ns", gz(ITEMS)[:-20], "gzip", FETCHED)
    con.close()
    assert rows(db(tmp_path), "SELECT count(*) FROM snapshot") == [(0,)]


def test_store_item_404_has_no_body(tmp_path):
    con = raw.connect(db(tmp_path))
    assert raw.store_item(con, 999, None, 404, None, None, FETCHED) == 1
    con.close()
    assert rows(db(tmp_path), "SELECT item_id, namespace, status, encoding, body FROM item") == [
        (999, None, 404, None, None)
    ]


def test_newest_last_modified(tmp_path):
    con = raw.connect(db(tmp_path))
    later = datetime(2026, 11, 24, 13, 22, 55, tzinfo=UTC)
    raw.store_snapshot(con, "items", later, "ns", gz(ITEMS), "gzip", FETCHED)
    raw.store_snapshot(con, "items", LM, "ns", gz(ITEMS), "gzip", FETCHED)
    assert raw.newest_last_modified(con, "items") == later
    assert raw.newest_last_modified(con, "commodities") is None
    con.close()


def test_prune_deletes_rows_before_they_turn_thirty_days_old(tmp_path):
    old = datetime(2026, 11, 24, 12, 59, 59, tzinfo=UTC)
    kept = datetime(2026, 11, 24, 13, 0, 1, tzinfo=UTC)
    con = raw.connect(db(tmp_path))
    for t in (old, kept):
        raw.store_snapshot(con, "items", t, "ns", gz(ITEMS), "gzip", FETCHED)
        raw.store_item(con, 1, "ns", 200, b"{}", "identity", t)
    # Cutoff: now + 1 h - 30 days = 2026-11-24T13:00:00Z.
    assert raw.prune(con, datetime(2026, 12, 24, 12, 0, tzinfo=UTC)) == (1, 1)
    con.close()
    assert rows(db(tmp_path), "SELECT last_modified FROM snapshot") == [(raw.iso(kept),)]
    assert rows(db(tmp_path), "SELECT fetched_at FROM item") == [(raw.iso(kept),)]


def test_ids_never_reused(tmp_path):
    con = raw.connect(db(tmp_path))
    for h in (12, 13):
        t = LM.replace(hour=h)
        raw.store_snapshot(con, "items", t, "ns", gz(ITEMS), "gzip", FETCHED)
    with con:
        con.execute("DELETE FROM snapshot WHERE id = 2")
    sid = raw.store_snapshot(con, "items", LM.replace(hour=14), "ns", gz(ITEMS), "gzip", FETCHED)
    con.close()
    assert sid == 3


def test_wal_mode(tmp_path):
    raw.connect(db(tmp_path)).close()
    assert rows(db(tmp_path), "PRAGMA journal_mode") == [("wal",)]


# Fetch -----------------------------------------------------------------------


class Resp:
    def __init__(self, body: bytes, headers: dict):
        self._body = body
        self.headers = Message()
        for k, v in headers.items():
            self.headers[k] = v

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int, headers: dict | None = None):
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("https://x", code, f"HTTP {code}", msg, io.BytesIO(b""))


class FakeBlizzard:
    """Answers the token URL and both listing endpoints from a script."""

    def __init__(self, listings: dict[str, list]):
        self.listings = listings  # endpoint -> list of responses or exceptions, in order
        self.requests: list = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if req.full_url == raw.TOKEN_URL:
            return Resp(json.dumps({"access_token": TOKEN}).encode(), {})
        endpoint = "commodities" if "/commodities" in req.full_url else "items"
        answer = self.listings[endpoint].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def snapshot(body: dict, lm: datetime = LM) -> Resp:
    return Resp(
        gzip.compress(json.dumps(body).encode()),
        {
            "Content-Encoding": "gzip",
            "Last-Modified": format_datetime(lm, usegmt=True),
            "Battlenet-Namespace": "dynamic-forever-eu",
        },
    )


def client(fake) -> raw.Client:
    return raw.Client("id", SECRET, opener=fake, sleep=lambda s: None)


def stored(tmp_path) -> list[tuple]:
    return rows(db(tmp_path), "SELECT endpoint, encoding, body FROM snapshot ORDER BY endpoint")


def seed(tmp_path, *endpoints, lm=LM):
    con = raw.connect(db(tmp_path))
    for e in endpoints:
        raw.store_snapshot(con, e, lm, "ns", gz(ITEMS), "gzip", FETCHED)
    con.close()


def newest(tmp_path, endpoint):
    con = raw.connect(db(tmp_path))
    try:
        return raw.newest_last_modified(con, endpoint)
    finally:
        con.close()


def test_new_snapshot_stores_both_endpoints(tmp_path):
    items, commodities = snapshot(ITEMS), snapshot(COMMODITIES)
    fake = FakeBlizzard({"items": [items], "commodities": [commodities]})
    assert raw.collect(client(fake), db(tmp_path), now=lambda: FETCHED, wait=False)
    assert stored(tmp_path) == [
        ("commodities", "gzip", commodities.read()),
        ("items", "gzip", items.read()),
    ]
    listing_req = fake.requests[1]
    assert listing_req.get_header("Authorization") == f"Bearer {TOKEN}"
    assert listing_req.get_header("Accept-encoding") == "gzip"
    assert "namespace=dynamic-forever-eu" in listing_req.full_url


def test_uncompressed_answer_is_stored_as_identity(tmp_path):
    plain = json.dumps(ITEMS).encode()
    resp = Resp(plain, {"Last-Modified": format_datetime(LM, usegmt=True)})
    fake = FakeBlizzard({"items": [resp], "commodities": [http_error(304)]})
    assert raw.collect(client(fake), db(tmp_path), now=lambda: FETCHED, wait=False)
    assert stored(tmp_path) == [("items", "identity", plain)]


def test_not_modified_stores_nothing_and_sends_if_modified_since(tmp_path):
    seed(tmp_path, "items", "commodities")
    fake = FakeBlizzard({"items": [http_error(304)], "commodities": [snapshot(COMMODITIES)]})
    assert raw.collect(client(fake), db(tmp_path), now=lambda: FETCHED, wait=False)
    assert rows(db(tmp_path), "SELECT count(*) FROM snapshot") == [(2,)]
    assert fake.requests[1].get_header("If-modified-since") == format_datetime(LM, usegmt=True)


def test_waits_for_a_new_snapshot_until_minute_55(tmp_path):
    seed(tmp_path, "items")
    newer = datetime(2026, 11, 24, 13, 22, 50, tzinfo=UTC)
    clock = iter([datetime(2026, 11, 24, 13, m, tzinfo=UTC) for m in (27, 27, 28, 32, 33)])
    slept = []
    fake = FakeBlizzard(
        {
            "items": [http_error(304), snapshot(ITEMS, newer)],
            "commodities": [snapshot(COMMODITIES, newer)],
        }
    )
    assert raw.collect(client(fake), db(tmp_path), now=lambda: next(clock), sleep=slept.append)
    assert slept == [raw.RETRY_EVERY_S]
    assert newest(tmp_path, "items") == newer


def test_broken_body_is_retried_then_fails(tmp_path, capsys):
    broken = snapshot(ITEMS)
    broken._body = broken._body[:-20]
    clock = iter([datetime(2026, 11, 24, 13, m, tzinfo=UTC) for m in (27, 27, 28, 52)])
    fake = FakeBlizzard({"items": [broken, http_error(304)], "commodities": [http_error(304)] * 2})
    assert (
        raw.collect(client(fake), db(tmp_path), now=lambda: next(clock), sleep=lambda s: None)
        is False
    )
    assert rows(db(tmp_path), "SELECT count(*) FROM snapshot") == [(0,)]
    assert "items: broken body, not stored" in capsys.readouterr().out


def test_retries_on_429_and_refreshes_token_on_401(tmp_path):
    fake = FakeBlizzard(
        {
            "items": [http_error(429, {"Retry-After": "1"}), http_error(401), snapshot(ITEMS)],
            "commodities": [snapshot(COMMODITIES)],
        }
    )
    assert raw.collect(client(fake), db(tmp_path), now=lambda: FETCHED, wait=False)
    tokens = [r for r in fake.requests if r.full_url == raw.TOKEN_URL]
    assert len(tokens) == 2


def test_errors_never_show_the_secret_or_token(tmp_path, capsys):
    fake = FakeBlizzard({"items": [http_error(403)], "commodities": [http_error(500)] * 5})
    assert raw.collect(client(fake), db(tmp_path), now=lambda: FETCHED, wait=False) is False
    out = capsys.readouterr().out
    assert "items: failed (403)" in out
    assert "commodities: failed (500)" in out
    for secret in (SECRET, TOKEN, "aWQ6"):  # aWQ6 = base64 of "id:"
        assert secret not in out


def test_collect_log_has_no_body(tmp_path, capsys):
    fake = FakeBlizzard({"items": [snapshot(ITEMS)], "commodities": [snapshot(COMMODITIES)]})
    raw.collect(client(fake), db(tmp_path), now=lambda: FETCHED, wait=False)
    out = capsys.readouterr().out
    assert "items: stored" in out and "bytes (gzip), Last-Modified 2026-11-24T12:22:55Z" in out
    assert "auctions" not in out


def test_old_day_files_go_after_first_store(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    for name in ("2026-11-23.sqlite", "2026-11-23.sqlite-wal", "notes.txt"):
        (old / name).write_bytes(b"x")
    fake = FakeBlizzard({"items": [http_error(304)], "commodities": [http_error(304)]})
    raw.collect(client(fake), db(tmp_path), now=lambda: FETCHED, wait=False, old_dir=old)
    assert len(list(old.iterdir())) == 3  # nothing stored: old store stays
    fake = FakeBlizzard({"items": [snapshot(ITEMS)], "commodities": [http_error(304)]})
    raw.collect(client(fake), db(tmp_path), now=lambda: FETCHED, wait=False, old_dir=old)
    assert [p.name for p in old.iterdir()] == ["notes.txt"]


def test_remove_old_store_drops_empty_folder(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "2026-11-23.sqlite").write_bytes(b"x")
    assert raw.remove_old_store(old) == 1
    assert not old.exists()
    assert raw.remove_old_store(old) == 0


def test_missing_credentials_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("BLIZZARD_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLIZZARD_CLIENT_SECRET", raising=False)
    assert raw.main(["--db", str(db(tmp_path)), "collect"]) == 1
    assert "set-blizzard-secret.sh" in capsys.readouterr().out


@pytest.mark.parametrize("text", ["x", None])
def test_retry_after_falls_back(text):
    assert raw._retry_after(text, 7.0) == 7.0
