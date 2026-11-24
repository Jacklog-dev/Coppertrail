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
MAX_RETRY_AFTER_S = 60.0
LOCK_WAIT_MINUTE = 35  # collect waits this long for an overrunning items run

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


class ItemError(FetchError):
    """One item lookup failed; the next item may still work."""


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

    def token(self) -> str:
        """The current token, or a new one."""
        return self._token or self._new_token()

    def forget_token(self) -> None:
        self._token = None

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
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            KeyError,
            ValueError,
        ) as exc:
            raise FetchError(f"token request failed: {type(exc).__name__}") from None
        return self._token

    def fetch(
        self, endpoint: str, since: datetime | None
    ) -> tuple[int, datetime | None, str, bytes | None, str | None]:
        """GET one listing endpoint, body as received (never decompressed).

        Returns (status, last_modified, namespace, body, encoding); 304 has no body."""
        query = urllib.parse.urlencode({"namespace": NAMESPACE, "locale": LOCALE})
        url = f"{API}{ENDPOINTS[endpoint]}?{query}"
        refreshed = False
        status: object = None
        for attempt in range(self._retries + 1):
            headers = {"Authorization": f"Bearer {self.token()}", "Accept-Encoding": "gzip"}
            if since is not None:
                headers["If-Modified-Since"] = format_datetime(since, usegmt=True)
            req = urllib.request.Request(url, headers=headers)
            try:
                with self._open(req, timeout=self._timeout) as r:
                    data = r.read()
                    gz = (r.headers.get("Content-Encoding") or "").lower() == "gzip"
                    lm = r.headers.get("Last-Modified")
                    if not lm:
                        raise FetchError(f"{endpoint}: no Last-Modified header")
                    ns = r.headers.get("Battlenet-Namespace") or NAMESPACE
                    lm_dt = parsedate_to_datetime(lm).astimezone(UTC)
                    return 200, lm_dt, ns, data, "gzip" if gz else "identity"
            except urllib.error.HTTPError as exc:
                status = exc.code
                if exc.code == 304:
                    return 304, None, NAMESPACE, None, None
                if exc.code == 401 and not refreshed:
                    refreshed = True
                    self.forget_token()
                    continue
                if exc.code not in _RETRY:
                    break
                wait = _retry_after(exc.headers.get("Retry-After"), 2.0**attempt * 5)
                log(f"{endpoint}: HTTP {exc.code}, waiting {wait:.0f}s")
                self._sleep(wait)
            except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
                status = type(exc).__name__
                log(f"{endpoint}: {status}, retrying")
                self._sleep(2.0**attempt * 5)
        raise FetchError(f"{endpoint}: failed ({status})")


def _retry_after(value: str | None, default: float) -> float:
    try:
        return min(MAX_RETRY_AFTER_S, max(0.0, float(value))) if value else default
    except ValueError:
        return default


# Collect ---------------------------------------------------------------------

_DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.sqlite(-wal|-shm|-journal)?$")


def remove_old_store(old_dir: Path) -> int:
    """Delete the first version's day files (and the folder once empty). Returns files deleted."""
    if not old_dir.is_dir():
        return 0
    gone = 0
    for p in old_dir.iterdir():
        if _DAY_FILE.match(p.name):
            p.unlink()
            gone += 1
    lock = old_dir / ".lock"
    if lock.exists() and all(p == lock for p in old_dir.iterdir()):
        lock.unlink()
    if not any(old_dir.iterdir()):
        old_dir.rmdir()
    return gone


def collect(
    client: Client,
    db: Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    wait: bool = True,
    old_dir: Path | None = None,
) -> bool:
    """Fetch both endpoints, retrying every RETRY_EVERY_S while Blizzard has nothing new
    (or sent a broken body), until minute LAST_MINUTE. True if nothing failed."""
    start = now()
    deadline = start.replace(minute=LAST_MINUTE, second=0, microsecond=0)
    pending = list(ENDPOINTS)
    broken: set[str] = set()
    ok = True
    con = connect(db)
    try:
        while pending:
            for endpoint in list(pending):
                since = newest_last_modified(con, endpoint)
                try:
                    status, lm, ns, body, encoding = client.fetch(endpoint, since)
                except FetchError as exc:
                    log(str(exc))
                    ok = False
                    pending.remove(endpoint)
                    continue
                if status == 304 or lm is None or (since is not None and lm <= since):
                    continue
                try:
                    sid = store_snapshot(con, endpoint, lm, ns, body or b"", encoding, now())
                except ValueError:
                    log(f"{endpoint}: broken body, not stored")
                    broken.add(endpoint)
                    continue
                broken.discard(endpoint)
                if sid is None:
                    log(f"{endpoint}: {iso(lm)} already stored")
                else:
                    size = len(body or b"")
                    log(f"{endpoint}: stored {size} bytes ({encoding}), Last-Modified {iso(lm)}")
                    if old_dir is not None:
                        gone = remove_old_store(old_dir)
                        if gone:
                            log(f"removed {gone} files of the old store in {old_dir}")
                pending.remove(endpoint)
            if not pending or not wait or now() + timedelta(seconds=RETRY_EVERY_S) > deadline:
                break
            sleep(RETRY_EVERY_S)
    finally:
        con.close()
    for endpoint in pending:
        if endpoint in broken:
            ok = False
        else:
            log(f"{endpoint}: not modified")
    return ok


# Items -----------------------------------------------------------------------

REFRESH_DAYS = 25
RETRY_404_DAYS = 7
ITEM_LAST_MINUTE = 20
ITEM_NAMESPACES = ("static-forever-eu", "static-classic1x-eu")
MAX_ITEM_FAILURES = 5  # in a row: Blizzard is in trouble, stop for this hour


def item_ids(body: bytes, encoding: str) -> set[int]:
    """The item ids in one listing response."""
    data = gzip.decompress(body) if encoding == "gzip" else body
    return {a["item"]["id"] for a in json.loads(data).get("auctions") or []}


def listed_ids(con: sqlite3.Connection) -> set[int]:
    """Item ids in the newest stored response of each endpoint."""
    ids: set[int] = set()
    for endpoint in ENDPOINTS:
        row = con.execute(
            "SELECT body, encoding FROM snapshot WHERE endpoint = ?"
            " ORDER BY last_modified DESC LIMIT 1",
            (endpoint,),
        ).fetchone()
        if row:
            ids |= item_ids(row[0], row[1])
    return ids


def due_items(con: sqlite3.Connection, ids: set[int], now: datetime) -> list[int]:
    """Ids to look up: missing first, then 200 rows older than REFRESH_DAYS, then 404 rows
    older than RETRY_404_DAYS (each oldest first). Only the newest row per item counts."""
    newest = {
        item_id: (status, fetched_at)
        for item_id, status, fetched_at in con.execute(
            "SELECT item_id, status, max(fetched_at) FROM item GROUP BY item_id"
        )
    }
    refresh = iso(now - timedelta(days=REFRESH_DAYS))
    retry = iso(now - timedelta(days=RETRY_404_DAYS))
    missing = sorted(i for i in ids if i not in newest)
    stale = [(newest[i][1], i) for i in ids if i in newest and newest[i][0] == 200]
    gone = [(newest[i][1], i) for i in ids if i in newest and newest[i][0] != 200]
    return (
        missing
        + [i for at, i in sorted(stale) if at <= refresh]
        + [i for at, i in sorted(gone) if at <= retry]
    )


class ItemClient:
    """Item lookups over one kept-alive HTTPS connection."""

    def __init__(
        self,
        client: Client,
        connect: Callable[[], object] = lambda: http.client.HTTPSConnection(API_HOST, timeout=30),
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 4,
    ):
        self._client = client
        self._connect = connect
        self._sleep = sleep
        self._retries = retries
        self._conn = None

    def _send(self, path: str) -> object:
        """One request; reconnects once if the kept-alive connection was dropped."""
        headers = {"Authorization": f"Bearer {self._client.token()}", "Accept-Encoding": "gzip"}
        for again in (True, False):
            if self._conn is None:
                self._conn = self._connect()
            try:
                self._conn.request("GET", path, headers=headers)
                resp = self._conn.getresponse()
                resp.body = resp.read()  # read fully, so the connection can be reused
                return resp
            except (http.client.HTTPException, OSError):
                self._conn.close()
                self._conn = None
                if not again:
                    raise

    def _get(self, item_id: int, namespace: str) -> tuple[int, bytes, str]:
        query = urllib.parse.urlencode({"namespace": namespace, "locale": LOCALE})
        path = f"/data/wow/item/{item_id}?{query}"
        refreshed = False
        status: object = None
        for attempt in range(self._retries + 1):
            try:
                resp = self._send(path)
            except (http.client.HTTPException, OSError) as exc:
                status = type(exc).__name__
                self._sleep(2.0**attempt * 5)
                continue
            status = resp.status
            if status in (200, 404):
                gz = (resp.getheader("Content-Encoding") or "").lower() == "gzip"
                return status, resp.body, "gzip" if gz else "identity"
            if status == 401 and not refreshed:
                refreshed = True
                self._client.forget_token()
                continue
            if status not in _RETRY:
                break
            self._sleep(_retry_after(resp.getheader("Retry-After"), 2.0**attempt * 5))
        raise ItemError(f"item {item_id}: failed ({status})")

    def lookup(self, item_id: int) -> tuple[int, str | None, bytes | None, str | None]:
        """(status, namespace, body, encoding): the first namespace that knows the item,
        or (404, None, None, None)."""
        for namespace in ITEM_NAMESPACES:
            status, body, encoding = self._get(item_id, namespace)
            if status == 200:
                return 200, namespace, body, encoding
        return 404, None, None, None


def run_items(
    items: ItemClient,
    db: Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    deadline: datetime | None = None,
) -> bool:
    """Look up every due item, one at a time, until done or `deadline` (default :20).
    Each answer is committed on its own. True unless a lookup failed."""
    start = now()
    if deadline is None:
        deadline = start.replace(minute=ITEM_LAST_MINUTE, second=0, microsecond=0)
    con = connect(db)
    done = found = failed = 0
    ok = True
    try:
        due = due_items(con, listed_ids(con), start)
        for item_id in due:
            if now() >= deadline:
                break
            try:
                status, namespace, body, encoding = items.lookup(item_id)
            except ItemError as exc:
                log(str(exc))  # skip this one; it stays due and is tried next hour
                ok = False
                failed += 1
                if failed >= MAX_ITEM_FAILURES:
                    log("items: too many failed lookups in a row, stopping")
                    break
                continue
            except FetchError as exc:
                log(str(exc))  # token or connection trouble: stop for this hour
                ok = False
                break
            failed = 0
            store_item(con, item_id, namespace, status, body, encoding, now())
            done += 1
            found += status == 200
    finally:
        con.close()
    log(
        f"items: {done} looked up ({found} found, {done - found} not found), {len(due) - done} left"
    )
    return ok


# Export ----------------------------------------------------------------------

_SNAPSHOT_COLS = ("id", "endpoint", "last_modified", "fetched_at", "namespace", "encoding")
_ITEM_COLS = ("seq", "item_id", "namespace", "status", "fetched_at", "encoding")


def _line(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode() + b"\n"


def export(db: Path, out: BinaryIO, after_snapshot: int, after_item: int) -> tuple[int, int]:
    """Stream every snapshot row after `after_snapshot`, then every item row after
    `after_item`: per row one JSON header line, then exactly `size` bytes of body. A last
    line {"end": true, "snapshot_max": N, "item_max": M} closes the stream. Read-only, one
    read transaction, one row in memory at a time. Returns the rows written."""
    con = connect_ro(db)
    snaps = items = 0
    snapshot_max = item_max = 0
    if con is not None:
        try:
            con.execute("BEGIN")  # one consistent view for the whole export
            for row in con.execute(
                f"SELECT {', '.join(_SNAPSHOT_COLS)}, body FROM snapshot WHERE id > ? ORDER BY id",
                (after_snapshot,),
            ):
                body = row[-1]
                out.write(
                    _line(
                        {
                            "table": "snapshot",
                            **dict(zip(_SNAPSHOT_COLS, row[:-1], strict=True)),
                            "size": len(body),
                        }
                    )
                )
                out.write(body)
                snaps += 1
            for row in con.execute(
                f"SELECT {', '.join(_ITEM_COLS)}, body FROM item WHERE seq > ? ORDER BY seq",
                (after_item,),
            ):
                body = row[-1] or b""
                out.write(
                    _line(
                        {
                            "table": "item",
                            **dict(zip(_ITEM_COLS, row[:-1], strict=True)),
                            "size": len(body),
                        }
                    )
                )
                out.write(body)
                items += 1
            snapshot_max = con.execute("SELECT coalesce(max(id), 0) FROM snapshot").fetchone()[0]
            item_max = con.execute("SELECT coalesce(max(seq), 0) FROM item").fetchone()[0]
        finally:
            con.close()
    out.write(_line({"end": True, "snapshot_max": snapshot_max, "item_max": item_max}))
    out.flush()
    return snaps, items


# Main ------------------------------------------------------------------------


def _lock(db: Path):
    import fcntl  # POSIX only; the Pi runs Linux

    db.parent.mkdir(parents=True, exist_ok=True)
    fh = open(db.parent / ".lock", "w")  # noqa: SIM115 - held for the whole run
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def _credentials() -> tuple[str, str] | None:
    client_id = os.environ.get("BLIZZARD_CLIENT_ID", "")
    client_secret = os.environ.get("BLIZZARD_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log("BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET are not set (run set-blizzard-secret.sh)")
        return None
    return client_id, client_secret


def _locked(
    db: Path,
    run: Callable[[], bool],
    wait_until_minute: int | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run under the lock. With `wait_until_minute`, wait for a held lock until that
    minute of the hour instead of giving up at once."""
    start = now()
    while (lock := _lock(db)) is None:
        if wait_until_minute is None or now() >= start.replace(
            minute=wait_until_minute, second=0, microsecond=0
        ):
            log("another run holds the lock")
            return 2
        sleep(10)
    try:
        return 0 if run() else 1
    finally:
        lock.close()


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=os.environ.get("COPPERTRAIL_DB", DEFAULT_DB))
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="store new listing responses (hourly at :27)")
    c.add_argument("--keep-days", type=int, default=KEEP_DAYS)
    c.add_argument("--once", action="store_true", help="do not wait for a new snapshot")
    sub.add_parser("items", help="look up due item details (hourly at :00, until :20)")
    e = sub.add_parser("export", help="stream rows after the bookmarks to stdout (read-only)")
    e.add_argument("--after-snapshot", type=int, default=0)
    e.add_argument("--after-item", type=int, default=0)
    sub.add_parser("check", help="only test the credentials")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    db = Path(args.db)
    if args.command == "export":
        # Read-only and needs no credentials: the PC runs it over SSH.
        snaps, items = export(db, sys.stdout.buffer, args.after_snapshot, args.after_item)
        print(f"exported {snaps} snapshots and {items} item rows", file=sys.stderr, flush=True)
        return 0
    creds = _credentials()
    if creds is None:
        return 1
    client = Client(*creds)
    if args.command == "check":
        try:
            client.token()
        except FetchError as exc:
            log(str(exc))
            return 1
        log("credentials ok: Blizzard issued a token")
        return 0

    def run_collect() -> bool:
        # Delete first, so a run that waits or fails still keeps the 30-day limit.
        con = connect(db)
        try:
            snaps, items = prune(con, datetime.now(UTC), args.keep_days)
        finally:
            con.close()
        if snaps or items:
            log(f"deleted {snaps} snapshots and {items} item rows (30-day limit)")
        return collect(client, db, wait=not args.once, old_dir=Path(OLD_RAW_DIR))

    if args.command == "items":
        return _locked(db, lambda: run_items(ItemClient(client), db))
    return _locked(db, run_collect, wait_until_minute=LOCK_WAIT_MINUTE)


if __name__ == "__main__":
    sys.exit(main())
