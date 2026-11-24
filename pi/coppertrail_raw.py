#!/usr/bin/env python3
"""Coppertrail's raw data database on the Raspberry Pi: Blizzard's data as sent.

One SQLite file holds every listing response of house 111 (items and commodities, one
row per hourly response, the body exactly as received) and the item details of every
listed item, for 30 days. Standard library only (the Pi is armv6l).

Subcommands:
  collect  hourly at :27: delete rows that would turn 30 days old, fetch both listing
           endpoints, store each new response as received.
  items    hourly at :00, stops at :20: look up item details that are missing or due.
  export   read-only: stream every row after the PC's bookmark to stdout.
  check    test the credentials.

Credentials come from BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET and are never logged;
errors name only the endpoint and the HTTP status. Logs never contain a body.

Exit codes: 0 ok or nothing new, 1 failed, 2 another run holds the lock.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import http.client
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import BinaryIO

TOKEN_URL = "https://oauth.battle.net/token"
API_HOST = "eu.api.blizzard.com"
API = f"https://{API_HOST}"
NAMESPACE = "dynamic-forever-eu"
LOCALE = "en_GB"
HOUSE_PATH = "/data/wow/ruleset/2/auctions/111"
ENDPOINTS = {"items": HOUSE_PATH, "commodities": HOUSE_PATH + "/commodities"}
DEFAULT_DB = "/var/lib/coppertrail/raw.sqlite"
OLD_RAW_DIR = "/var/lib/coppertrail/raw"
KEEP_DAYS = 30
RETRY_EVERY_S = 300
LAST_MINUTE = 55
_RETRY = {429, 500, 502, 503, 504}

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- the PC's bookmark, never reused
    endpoint      TEXT NOT NULL,         -- 'items' | 'commodities'
    last_modified TEXT NOT NULL,         -- Blizzard's Last-Modified, ISO 8601 UTC
    fetched_at    TEXT NOT NULL,         -- when the Pi received it, ISO 8601 UTC
    namespace     TEXT NOT NULL,
    encoding      TEXT NOT NULL,         -- 'gzip' or 'identity': how body is stored
    size          INTEGER NOT NULL,      -- bytes of body
    body          BLOB NOT NULL,         -- the response body exactly as received
    UNIQUE (endpoint, last_modified)
);
CREATE TABLE IF NOT EXISTS item (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,     -- the PC's bookmark, never reused
    item_id    INTEGER NOT NULL,
    namespace  TEXT,                     -- static namespace that answered; NULL if none
    status     INTEGER NOT NULL,         -- 200, or 404 if found nowhere
    fetched_at TEXT NOT NULL,
    encoding   TEXT,                     -- as in snapshot; NULL when there is no body
    body       BLOB                      -- the response body exactly as received
);
CREATE INDEX IF NOT EXISTS item_by_id ON item (item_id, fetched_at);
"""


class FetchError(Exception):
    """A failed request. The message never carries a credential or the token."""


def log(msg: str) -> None:
    print(msg, flush=True)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


# Store -----------------------------------------------------------------------


def connect(db: Path) -> sqlite3.Connection:
    """Open (and create) the database for writing."""
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    con.executescript(SCHEMA)
    return con


def connect_ro(db: Path) -> sqlite3.Connection | None:
    """Open the database read-only, or None if it does not exist."""
    if not db.is_file():
        return None
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)


def check_body(body: bytes, encoding: str) -> None:
    """Raise ValueError if a gzip body does not decompress (cut off in transit)."""
    if encoding == "gzip":
        try:
            gzip.decompress(body)
        except (OSError, EOFError) as exc:
            raise ValueError(f"broken gzip body: {type(exc).__name__}") from None


def store_snapshot(
    con: sqlite3.Connection,
    endpoint: str,
    last_modified: datetime,
    namespace: str,
    body: bytes,
    encoding: str,
    fetched_at: datetime,
) -> int | None:
    """Store one listing response. Returns its id, or None if already stored."""
    check_body(body, encoding)
    with con:
        cur = con.execute(
            "INSERT OR IGNORE INTO snapshot"
            " (endpoint, last_modified, fetched_at, namespace, encoding, size, body)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (endpoint, iso(last_modified), iso(fetched_at), namespace, encoding, len(body), body),
        )
    return cur.lastrowid if cur.rowcount else None


def store_item(
    con: sqlite3.Connection,
    item_id: int,
    namespace: str | None,
    status: int,
    body: bytes | None,
    encoding: str | None,
    fetched_at: datetime,
) -> int:
    """Store one item lookup. Returns its seq."""
    with con:
        cur = con.execute(
            "INSERT INTO item (item_id, namespace, status, fetched_at, encoding, body)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, namespace, status, iso(fetched_at), encoding, body),
        )
    return cur.lastrowid


def newest_last_modified(con: sqlite3.Connection, endpoint: str) -> datetime | None:
    (value,) = con.execute(
        "SELECT max(last_modified) FROM snapshot WHERE endpoint = ?", (endpoint,)
    ).fetchone()
    return parse_iso(value) if value else None


def prune(
    con: sqlite3.Connection,
    now: datetime,
    keep_days: int = KEEP_DAYS,
    lead: timedelta = timedelta(hours=1),
) -> tuple[int, int]:
    """Delete every row that turns `keep_days` old before the next run (`lead` from now).

    Returns (snapshots deleted, item rows deleted)."""
    cutoff = iso(now + lead - timedelta(days=keep_days))
    with con:
        snaps = con.execute("DELETE FROM snapshot WHERE last_modified <= ?", (cutoff,)).rowcount
        items = con.execute("DELETE FROM item WHERE fetched_at <= ?", (cutoff,)).rowcount
    return snaps, items


# Fetch -----------------------------------------------------------------------


Opener = Callable[..., object]


class Client:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        opener: Opener = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 120.0,
        retries: int = 4,
    ):
        self._auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._open = opener
        self._sleep = sleep
        self._timeout = timeout
        self._retries = retries
        self._token: str | None = None

    def _new_token(self) -> str:
        req = urllib.request.Request(
            TOKEN_URL,
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {self._auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with self._open(req, timeout=self._timeout) as r:
                self._token = json.loads(r.read())["access_token"]
        except urllib.error.HTTPError as exc:
            raise FetchError(f"token request failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            raise FetchError(f"token request failed: {type(exc).__name__}") from None
        return self._token

    def fetch(
        self, endpoint: str, since: datetime | None
    ) -> tuple[int, datetime | None, str, dict | None]:
        """GET one listing endpoint. Returns (status, last_modified, namespace, body);
        status 304 has no body."""
        query = urllib.parse.urlencode({"namespace": NAMESPACE, "locale": LOCALE})
        url = f"{API}{ENDPOINTS[endpoint]}?{query}"
        refreshed = False
        status: object = None
        for attempt in range(self._retries + 1):
            headers = {
                "Authorization": f"Bearer {self._token or self._new_token()}",
                "Accept-Encoding": "gzip",
            }
            if since is not None:
                headers["If-Modified-Since"] = format_datetime(since, usegmt=True)
            req = urllib.request.Request(url, headers=headers)
            try:
                with self._open(req, timeout=self._timeout) as r:
                    data = r.read()
                    if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                        data = gzip.decompress(data)
                    lm = r.headers.get("Last-Modified")
                    if not lm:
                        raise FetchError(f"{endpoint}: no Last-Modified header")
                    ns = r.headers.get("Battlenet-Namespace") or NAMESPACE
                    return 200, parsedate_to_datetime(lm).astimezone(UTC), ns, json.loads(data)
            except urllib.error.HTTPError as exc:
                status = exc.code
                if exc.code == 304:
                    return 304, None, NAMESPACE, None
                if exc.code == 401 and not refreshed:
                    refreshed = True
                    self._token = None
                    continue
                if exc.code not in _RETRY:
                    break
                wait = _retry_after(exc.headers.get("Retry-After"), 2.0**attempt * 5)
                log(f"{endpoint}: HTTP {exc.code}, waiting {wait:.0f}s")
                self._sleep(wait)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                status = type(exc).__name__
                log(f"{endpoint}: {status}, retrying")
                self._sleep(2.0**attempt * 5)
        raise FetchError(f"{endpoint}: failed ({status})")


def _retry_after(value: str | None, default: float) -> float:
    try:
        return max(0.0, float(value)) if value else default
    except ValueError:
        return default


# Run -------------------------------------------------------------------------


def collect(
    client: Client,
    raw_dir: Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    wait: bool = True,
) -> bool:
    """Fetch both endpoints, retrying every RETRY_EVERY_S while Blizzard has nothing
    new, until minute LAST_MINUTE of the hour. True if every request succeeded."""
    start = now()
    deadline = start.replace(minute=LAST_MINUTE, second=0, microsecond=0)
    pending = list(ENDPOINTS)
    ok = True
    while pending:
        for endpoint in list(pending):
            since = newest_last_modified(raw_dir, endpoint)
            try:
                status, lm, ns, body = client.fetch(endpoint, since)
            except FetchError as exc:
                log(str(exc))
                ok = False
                pending.remove(endpoint)
                continue
            if status == 304 or lm is None or (since is not None and lm <= since):
                continue
            written = store_snapshot(raw_dir, endpoint, lm, ns, body or {}, now())
            del body
            if written is None:
                log(f"{endpoint}: {iso(lm)} already stored")
            else:
                log(f"{endpoint}: stored {written} listings, Last-Modified {iso(lm)}")
            pending.remove(endpoint)
        if not pending or not wait or now() + timedelta(seconds=RETRY_EVERY_S) > deadline:
            break
        sleep(RETRY_EVERY_S)
    for endpoint in pending:
        log(f"{endpoint}: not modified")
    return ok


def _lock(raw_dir: Path):
    import fcntl  # POSIX only; the Pi runs Linux

    raw_dir.mkdir(parents=True, exist_ok=True)
    fh = open(raw_dir / ".lock", "w")  # noqa: SIM115 - held for the whole run
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw-dir", default=os.environ.get("COPPERTRAIL_RAW_DIR", DEFAULT_RAW_DIR))
    ap.add_argument("--keep-days", type=int, default=KEEP_DAYS)
    ap.add_argument("--once", action="store_true", help="do not wait for a new snapshot")
    ap.add_argument("--check", action="store_true", help="only test the credentials")
    args = ap.parse_args(argv)
    raw_dir = Path(args.raw_dir)

    client_id = os.environ.get("BLIZZARD_CLIENT_ID", "")
    client_secret = os.environ.get("BLIZZARD_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log("BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET are not set (run set-blizzard-secret.sh)")
        return 1
    if args.check:
        try:
            Client(client_id, client_secret)._new_token()
        except FetchError as exc:
            log(str(exc))
            return 1
        log("credentials ok: Blizzard issued a token")
        return 0

    lock = _lock(raw_dir)
    if lock is None:
        log("another run holds the lock")
        return 2
    try:
        # Delete first, so a run that waits or fails still keeps the 30-day limit.
        for endpoint, lm in prune(raw_dir, datetime.now(UTC), args.keep_days):
            log(f"{endpoint}: deleted snapshot {lm} (30-day limit)")
        ok = collect(Client(client_id, client_secret), raw_dir, wait=not args.once)
        return 0 if ok else 1
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
