"""CLI: python -m coppertrail.collector [--data-dir DIR] [-v] {hourly,nightly}.

Exit codes: 0 ok or not modified, 1 failed, 2 another run holds the lock.
The lock (`<data-dir>/.lock`) is taken here, so the runs themselves never lock.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
from pathlib import Path

from .config import load_config
from .lock import LockError, RunLock

DEFAULT_DATA_DIR = "private"
EXIT_OK, EXIT_FAILED, EXIT_LOCKED = 0, 1, 2

log = logging.getLogger("coppertrail.collector")


def _setup_logging(data_dir: Path, verbose: bool) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in [h for h in root.handlers if getattr(h, "_coppertrail", False)]:
        root.removeHandler(h)
        h.close()
    for h in (
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_dir / "collector.log", encoding="utf-8"),
    ):
        h.setFormatter(fmt)
        h._coppertrail = True
        root.addHandler(h)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m coppertrail.collector")
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("COPPERTRAIL_DATA", DEFAULT_DATA_DIR)),
        help="data repo checkout (main); copied data lives in <data-dir>/window (not in git)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hourly", help="fetch the latest snapshot and write its hour")
    sub.add_parser("nightly", help="rebuild the selection, refresh master data, prune the window")
    args = p.parse_args(argv)

    data_dir: Path = args.data_dir
    _setup_logging(data_dir, args.verbose)
    try:
        cfg = load_config(data_dir)
    except ValueError as exc:
        log.error("%s", exc)
        return EXIT_FAILED

    run = importlib.import_module(f"coppertrail.collector.{args.cmd}").main
    try:
        with RunLock(data_dir / ".lock"):
            return run(cfg)
    except LockError as exc:
        log.error("%s", exc)
        return EXIT_LOCKED
    except Exception:
        log.exception("%s run failed", args.cmd)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
