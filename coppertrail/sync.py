"""Fill our database from the Pi: read every new row of its export, keep only what we need.

    python -m coppertrail.sync            # one sync, prints what it stored

Per listing snapshot only the lowest buyout per unit of each item is kept (commodities
`unit_price`, other items `buyout / quantity`; bid-only listings have no price). Per item
lookup the name, quality and item class; items we do not keep (see `db.UNWANTED`) lose
their price rows. The export is read over SSH (`$COPPERTRAIL_PI`, default
`coppertrail@coppertrail-pi`); the Pi only streams stored bytes.
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO

from coppertrail import db

PI = "coppertrail@coppertrail-pi"
EXPORT = "python3 /opt/coppertrail/coppertrail_raw.py export"
ITEM_COMMIT_EVERY = 500

Progress = Callable[[int, int], None]  # (snapshots done, snapshots to read)
Source = Callable[[int, int], "Export"]


@dataclass
class SyncResult:
    ok: bool
    message: str
    snapshots: int = 0
    items: int = 0


class SyncError(Exception):
    pass


def epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def hour_of(iso: str) -> int:
    return epoch(iso) // 3600 * 3600


def decode(body: bytes, encoding: str | None) -> dict:
    return json.loads(gzip.decompress(body) if encoding == "gzip" else body)


def lowest_prices(listing: dict) -> dict[int, int]:
    """item id -> lowest price per unit (copper) in one listing response."""
    lows: dict[int, int] = {}
    for a in listing.get("auctions") or ():
        if "unit_price" in a:
            price = a["unit_price"]
        elif "buyout" in a and a.get("quantity"):
            price = a["buyout"] // a["quantity"]
        else:
            continue  # bid only
        item_id = a["item"]["id"]
        if price < lows.get(item_id, price + 1):
            lows[item_id] = price
    return lows


class Export:
    """The Pi's export stream over SSH, as a context manager around a readable pipe."""

    def __init__(self, after_snapshot: int, after_item: int, host: str | None = None) -> None:
        host = host or os.environ.get("COPPERTRAIL_PI") or PI
        cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host,
            f"{EXPORT} --after-snapshot {int(after_snapshot)} --after-item {int(after_item)}",
        ]  # fmt: skip
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=flags,
            )
        except OSError as exc:
            raise SyncError(f"ssh could not start: {exc}") from exc
        self.stream: BinaryIO = self.proc.stdout

    def __enter__(self) -> Export:
        return self

    def __exit__(self, *exc) -> None:
        self.proc.stdout.close()
        err = self.proc.stderr.read().decode("utf-8", "replace").strip()
        if self.proc.wait() != 0 and exc[0] is None:
            raise SyncError(err.splitlines()[-1] if err else "the Pi did not answer")


def _records(stream: BinaryIO):
    """(header, body) per row, then the end header."""
    while True:
        line = stream.readline()
        if not line:
            raise SyncError("the export ended early")
        header = json.loads(line)
        if header.get("end"):
            yield header, b""
            return
        body = stream.read(header["size"]) if header["size"] else b""
        if len(body) != header["size"]:
            raise SyncError("the export ended early")
        yield header, body


def store_item(con: sqlite3.Connection, header: dict, details: dict) -> None:
    """Name, quality and item class of one item lookup."""
    name = details.get("name")
    if not isinstance(name, str) or not name:
        return
    quality = (details.get("quality") or {}).get("type")
    class_id = (details.get("item_class") or {}).get("id")
    db.set_item(con, header["item_id"], name, quality, class_id, epoch(header["fetched_at"]))


def pi_maxima(source: Source = Export) -> tuple[int, int]:
    """The Pi's newest snapshot id and item seq (an export with nothing to send)."""
    big = 2**62
    with source(big, big) as exp:
        for header, _ in _records(exp.stream):
            return header["snapshot_max"], header["item_max"]
    raise SyncError("no end line")


def sync(
    con: sqlite3.Connection,
    source: Source = Export,
    progress: Progress | None = None,
    now: Callable[[], float] = time.time,
) -> SyncResult:
    """Read everything newer than our bookmarks into `con`; safe to stop at any point."""
    after_snapshot, after_item = db.bookmarks(con)
    snaps = items = pending = 0
    skip = db.unwanted_ids(con)
    try:
        newest, _ = pi_maxima(source)
        total = max(newest - after_snapshot, 0)
        if progress:
            progress(0, total)
        with source(after_snapshot, after_item) as exp:
            for header, body in _records(exp.stream):
                if header.get("end"):
                    break
                if header["table"] == "snapshot":
                    lows = lowest_prices(decode(body, header["encoding"]))
                    db.add_prices(con, hour_of(header["last_modified"]), lows, skip)
                    db.set_bookmark(con, "snapshot", header["id"])
                    con.commit()
                    snaps += 1
                    if progress:
                        progress(min(snaps, total), total)
                else:
                    if header["status"] == 200 and body:
                        store_item(con, header, decode(body, header["encoding"]))
                    db.set_bookmark(con, "item", header["seq"])
                    items += 1
                    pending += 1
                    if pending >= ITEM_COMMIT_EVERY:
                        con.commit()
                        pending = 0
            db.drop_unwanted(con)
            db.prune_items(con, int(now()))
            con.commit()
    except (SyncError, ValueError, KeyError, OSError) as exc:
        db.drop_unwanted(con)
        con.commit()  # what was read so far stays, the bookmarks match it
        return SyncResult(False, f"Sync failed: {exc}", snaps, items)
    return SyncResult(True, f"Synced {snaps} snapshots, {items} item rows", snaps, items)


def main() -> int:
    con = db.connect()

    def show(done: int, total: int) -> None:
        print(f"\r{done} / {total} snapshots", end="", flush=True)

    result = sync(con, progress=show)
    print()
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
