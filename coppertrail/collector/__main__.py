"""CLI: python -m coppertrail.collector run [--data-dir DIR] [--config FILE]."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import load_config
from .gaps import format_summary, gap_report
from .run import Collector
from .store import WATCHLIST, Store

DEFAULT_DATA_DIR = "private"


def _setup_logging(data_dir: Path, verbose: bool) -> Path:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"collector-{datetime.now(UTC):%Y-%m-%d}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(path, encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m coppertrail.collector")
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("COPPERTRAIL_DATA", DEFAULT_DATA_DIR)),
        help="data directory (default: $COPPERTRAIL_DATA or ./private)",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="TOML file with a [collector] table (default: <data-dir>/collector.toml if present)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="collect once (resumes an interrupted run)")
    r.add_argument("--max-items", type=int, help="limit the watchlist (for testing)")
    r.add_argument("--no-scans", action="store_true", help="skip per-scan (24h) data")
    sub.add_parser("gaps", help="print the gap report for the latest watchlist")
    args = p.parse_args(argv)

    data_dir: Path = args.data_dir
    cfg = load_config(args.config or data_dir / "collector.toml")
    _setup_logging(data_dir, args.verbose)

    if args.cmd == "run":
        if args.no_scans:
            cfg.fetch_scans = False
        if args.max_items:
            cfg.max_items = args.max_items
        return Collector(cfg, data_dir).run()

    if args.cmd == "gaps":
        store = Store(data_dir)
        tbl = store.query(
            "SELECT item_id FROM {w} WHERE run_id = (SELECT max(run_id) FROM {w})", w=WATCHLIST.name
        )
        if tbl is None:
            print("no watchlist yet")
            return 1
        rows, market = gap_report(
            store, tbl.column("item_id").to_pylist(), datetime.now(UTC), cfg.gap_window_hours, "cli"
        )
        print(format_summary(rows, market))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
