"""Single-instance lock for collector runs, portable across Windows and Linux."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

LOCK_STALE_S = 20 * 60  # a lock not refreshed for this long belongs to a dead run


class LockError(Exception):
    pass


class RunLock:
    """Portable single-instance lock: exclusive create, refreshed as a heartbeat."""

    def __init__(self, path: Path):
        self.path = path

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age < LOCK_STALE_S:
                raise LockError(
                    f"another collector run holds {self.path} (heartbeat {age:.0f}s ago)"
                )
            log.warning("removing stale lock %s (%.0f min old)", self.path, age / 60)
            self.path.unlink(missing_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(f"pid={os.getpid()} started={datetime.now(UTC).isoformat()}\n")

    def heartbeat(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.utime(self.path)

    def release(self) -> None:
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> RunLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
