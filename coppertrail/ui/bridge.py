"""Everything the page shows, as JSON-able dicts. No pywebview here.

`Bridge.EXPOSED` lists what JavaScript may call. Sync runs in a worker thread with its own
database connection; the page polls `status()` while it runs.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from coppertrail import db
from coppertrail import sync as syncmod
from coppertrail.ui import format as fmt
from coppertrail.ui import icons

RANGES = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "all": None}


def coin(copper: int | None) -> dict | None:
    if copper is None:
        return None
    return {"parts": fmt.coin_parts(int(copper)), "text": fmt.coins_text(int(copper))}


def when(at: int | None) -> str | None:
    return fmt.local_datetime(datetime.fromtimestamp(at, UTC)) if at is not None else None


def display_name(item_id: int, name: str | None) -> str:
    return name or f"Item {item_id}"


class Bridge:
    EXPOSED: ClassVar[tuple[str, ...]] = ("status", "items", "item", "icons", "sync_now")

    def __init__(self, path: Path | None = None, source: syncmod.Source = syncmod.Export) -> None:
        self.path = Path(path or db.default_path())
        self.source = source
        self.lock = threading.Lock()  # guards the sync state below
        self._thread: threading.Thread | None = None
        self._progress = (0, 0)
        self._message: str | None = None
        self._ok = True
        db.connect(self.path).close()  # creates the file and tables

    def _con(self):
        return db.connect(self.path)

    # Sync -------------------------------------------------------------------------------

    def syncing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def sync_now(self) -> dict:
        """Start a sync in the background (no-op while one runs)."""
        with self.lock:
            if not self.syncing():
                self._progress, self._message = (0, 0), None
                self._thread = threading.Thread(target=self._run_sync, daemon=True)
                self._thread.start()
        return self.status()

    def _run_sync(self) -> None:
        con = self._con()
        try:
            result = syncmod.sync(con, self.source, progress=self._set_progress)
        except Exception as exc:  # noqa: BLE001 - shown in the page, never a crash
            result = syncmod.SyncResult(False, f"Sync failed: {type(exc).__name__}: {exc}")
        finally:
            con.close()
        with self.lock:
            self._ok, self._message = result.ok, result.message

    def _set_progress(self, done: int, total: int) -> None:
        with self.lock:
            self._progress = (done, total)

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # Page data --------------------------------------------------------------------------

    def status(self) -> dict:
        con = self._con()
        try:
            hours, first, last = db.hour_span(con)
        finally:
            con.close()
        with self.lock:
            done, total = self._progress
            return {
                "hours": hours,
                "first": when(first),
                "last": when(last),
                "syncing": self.syncing(),
                "done": done,
                "total": total,
                "ok": self._ok,
                "message": self._message,
                "credit": fmt.CREDIT_TEXT,
            }

    def items(self) -> dict:
        """Every item in the newest hour with its lowest price, cheapest names first."""
        con = self._con()
        try:
            at = db.latest_hour(con)
            rows = db.listed_now(con)
        finally:
            con.close()
        out = [
            {
                "id": i,
                "name": display_name(i, n),
                "trade": cls == db.TRADE_GOODS,
                "copper": low,
                "price": coin(low),
            }
            for i, n, cls, low in rows
        ]
        out.sort(key=lambda r: r["name"].lower())
        return {"at": when(at), "rows": out}

    def item(self, item_id: int, range_key: str = "7d") -> dict:
        """One item: its lowest price now and the history of its lowest price."""
        item_id = int(item_id)
        span = RANGES.get(range_key, RANGES["7d"])
        con = self._con()
        try:
            name = db.item_name(con, item_id)
            latest = db.latest_hour(con)
            since = latest - span + 3600 if span and latest is not None else None
            points = db.history(con, item_id, since)
        finally:
            con.close()
        x = [at for at, _ in points]
        y = [low for _, low in points]
        now = y[-1] if y else None
        seen = [v for v in y if v is not None]
        first_seen = next((at for at, v in points if v is not None), None)
        change = None
        if seen and now is not None and seen[0]:
            text, direction = fmt.percent_change((now - seen[0]) / seen[0] * 100)
            change = {"text": f"{text} since {when(first_seen)}", "direction": direction}
        last_seen = next((at for at, v in reversed(points) if v is not None), None)
        return {
            "id": item_id,
            "name": display_name(item_id, name),
            "price": coin(now),
            "listed": now is not None,
            "lastSeen": when(last_seen),
            "at": when(latest),
            "range": range_key if range_key in RANGES else "7d",
            "ranges": list(RANGES),
            "change": change,
            "low": coin(min(seen)) if seen else None,
            "high": coin(max(seen)) if seen else None,
            "x": x,
            "y": y,
        }

    def icons(self) -> dict:
        return {
            "url": icons.ICON_URL,
            "ids": {str(k): v for k, v in icons.load_map().items()},
        }
