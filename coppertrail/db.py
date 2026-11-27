"""Our database on the PC: the lowest price of every listed item, per hour, kept forever.

One SQLite file (`coppertrail.sqlite` in the config folder). Filled only by `sync.py` from the
Pi's export; the raw listings themselves are never stored here.

- `price(item_id, at, low)`: the lowest buyout per unit in copper, `at` = the snapshot's hour
  (Unix seconds, UTC, on the hour). Our own result, kept forever.
- `hour(at)`: every hour we have a snapshot for, so the chart can show gaps where an item was
  not listed.
- `item(item_id, name, quality, class_id, fetched_at)`: the latest name, quality and item class
  from the Pi's item details. Copied Blizzard data: rows older than 30 days are deleted (the
  Pi refreshes them every 25 days).
- `bookmark(key, value)`: the highest Pi `snapshot` id and `item` seq already read.

Items we do not want (UNWANTED) are not kept: gray (poor) items, recipes, and weapons or
armour below epic quality. Their price rows are deleted as soon as their details are known.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ITEM_KEEP_S = 30 * 86400
TRADE_GOODS = 7  # item class ids from Blizzard's item details
WEAPON, ARMOR, RECIPE = 2, 4, 9

# SQL condition on the `item` table: the item is left out of our data.
UNWANTED = (
    f"(quality = 'POOR' OR class_id = {RECIPE}"
    f" OR (class_id IN ({WEAPON}, {ARMOR}) AND quality <> 'EPIC'))"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS price (
    item_id INTEGER NOT NULL,
    at      INTEGER NOT NULL,
    low     INTEGER NOT NULL,
    PRIMARY KEY (item_id, at)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS price_by_hour ON price (at);
CREATE TABLE IF NOT EXISTS hour (at INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS item (
    item_id    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    quality    TEXT,
    class_id   INTEGER,
    fetched_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bookmark (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


def unwanted(quality: str | None, class_id: int | None) -> bool:
    """The Python twin of UNWANTED."""
    return (
        quality == "POOR"
        or class_id == RECIPE
        or (class_id in (WEAPON, ARMOR) and quality != "EPIC")
    )


def config_dir() -> Path:
    """`$COPPERTRAIL_CONFIG`, else `%APPDATA%\\Coppertrail` (or `~/.config/coppertrail`)."""
    if env := os.environ.get("COPPERTRAIL_CONFIG"):
        return Path(env)
    if sys.platform == "win32" and (appdata := os.environ.get("APPDATA")):
        return Path(appdata) / "Coppertrail"
    return Path.home() / ".config" / "coppertrail"


def default_path() -> Path:
    return config_dir() / "coppertrail.sqlite"


def _migrate(con: sqlite3.Connection) -> None:
    """The first version kept names only (`name` table): read all item details again."""
    if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'name'").fetchone():
        con.execute("DROP TABLE name")
        con.execute("DELETE FROM bookmark WHERE key = 'item'")
        con.commit()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or default_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def bookmarks(con: sqlite3.Connection) -> tuple[int, int]:
    rows = dict(con.execute("SELECT key, value FROM bookmark"))
    return rows.get("snapshot", 0), rows.get("item", 0)


def set_bookmark(con: sqlite3.Connection, key: str, value: int) -> None:
    con.execute(
        "INSERT INTO bookmark (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def unwanted_ids(con: sqlite3.Connection) -> set[int]:
    return {r[0] for r in con.execute(f"SELECT item_id FROM item WHERE {UNWANTED}")}


def add_prices(
    con: sqlite3.Connection, at: int, lows: dict[int, int], skip: set[int] = frozenset()
) -> None:
    """Store one snapshot's lowest prices; a second snapshot of the same hour keeps the lower."""
    con.execute("INSERT OR IGNORE INTO hour (at) VALUES (?)", (at,))
    con.executemany(
        "INSERT INTO price (item_id, at, low) VALUES (?, ?, ?)"
        " ON CONFLICT(item_id, at) DO UPDATE SET low = min(low, excluded.low)",
        [(item_id, at, low) for item_id, low in lows.items() if item_id not in skip],
    )


def set_item(
    con: sqlite3.Connection,
    item_id: int,
    name: str,
    quality: str | None,
    class_id: int | None,
    fetched_at: int,
) -> None:
    con.execute(
        "INSERT INTO item (item_id, name, quality, class_id, fetched_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(item_id) DO UPDATE SET name = excluded.name, quality = excluded.quality,"
        " class_id = excluded.class_id, fetched_at = excluded.fetched_at"
        " WHERE excluded.fetched_at >= item.fetched_at",
        (item_id, name, quality, class_id, fetched_at),
    )


def drop_unwanted(con: sqlite3.Connection) -> int:
    """Delete the price rows of items we do not keep."""
    return con.execute(
        f"DELETE FROM price WHERE item_id IN (SELECT item_id FROM item WHERE {UNWANTED})"
    ).rowcount


def prune_items(con: sqlite3.Connection, now: int) -> int:
    return con.execute("DELETE FROM item WHERE fetched_at < ?", (now - ITEM_KEEP_S,)).rowcount


def latest_hour(con: sqlite3.Connection) -> int | None:
    return con.execute("SELECT max(at) FROM hour").fetchone()[0]


def hour_span(con: sqlite3.Connection) -> tuple[int, int | None, int | None]:
    """(number of hours, first hour, last hour)."""
    return con.execute("SELECT count(*), min(at), max(at) FROM hour").fetchone()


def listed_now(con: sqlite3.Connection) -> list[tuple[int, str | None, int | None, int]]:
    """(item_id, name, class id, lowest price) of every item in the newest hour.

    Unwanted items have no price rows (`drop_unwanted` runs at the end of every sync).
    """
    at = latest_hour(con)
    if at is None:
        return []
    return con.execute(
        "SELECT p.item_id, i.name, i.class_id, p.low"
        " FROM price p LEFT JOIN item i USING (item_id) WHERE p.at = ?",
        (at,),
    ).fetchall()


def item_name(con: sqlite3.Connection, item_id: int) -> str | None:
    row = con.execute("SELECT name FROM item WHERE item_id = ?", (item_id,)).fetchone()
    return row[0] if row else None


def history(con: sqlite3.Connection, item_id: int, since: int | None = None) -> list[tuple]:
    """(hour, lowest price or None) for every hour we have since `since`; None = not listed."""
    return con.execute(
        "SELECT h.at, p.low FROM hour h LEFT JOIN price p ON p.at = h.at AND p.item_id = ?"
        " WHERE h.at >= ? ORDER BY h.at",
        (item_id, since or 0),
    ).fetchall()
