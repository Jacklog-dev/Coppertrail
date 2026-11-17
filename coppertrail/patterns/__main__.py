"""CLI: python -m coppertrail.patterns [--data-dir DIR] list | run KEY | baseline."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from coppertrail.patterns import REGISTRY, Context, run
from coppertrail.query.catalog import archive_status, default_data_dir, load_items
from coppertrail.query.groups import load_groups


def _item_ids(data_dir: Path, group_names: list[str]) -> list[int] | None:
    if not group_names:
        return None
    groups = {g.name.casefold(): g for g in load_groups()}
    missing = [n for n in group_names if n.casefold() not in groups]
    if missing:
        raise SystemExit(f"unknown group(s): {', '.join(missing)}; have: {', '.join(groups)}")
    items = load_items(data_dir)
    ids: set[int] = set()
    for n in group_names:
        ids |= {i.item_id for i in groups[n.casefold()].members(items)}
    return sorted(ids)


def _window(data_dir: Path, start: date | None, end: date | None, days: int | None):
    st = archive_status(data_dir)
    hi = end or st.last_day or date.today()
    lo = start or (hi - timedelta(days=days - 1) if days else st.first_day or hi)
    return lo, hi


def _print_frame(df: pd.DataFrame, top: int) -> None:
    if df is None or df.empty:
        print("(no rows)")
        return
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(df.head(top).to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m coppertrail.patterns")
    p.add_argument("--data-dir", type=Path, default=default_data_dir())
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the registered patterns")
    r = sub.add_parser("run", help="run one pattern and print its basis line and top rows")
    r.add_argument("key")
    r.add_argument("--group", action="append", default=[], help="limit to an item group")
    r.add_argument("--from", dest="start", type=date.fromisoformat)
    r.add_argument("--to", dest="end", type=date.fromisoformat)
    r.add_argument("--days", type=int, help="last N days (default: the whole archive)")
    r.add_argument("--top", type=int, default=20)
    r.add_argument("--csv", type=Path, help="write the ranked table to this CSV file")
    b = sub.add_parser("baseline", help="reproduce the HANDOVER section 5 baseline")
    b.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2026, 11, 9))
    b.add_argument("--to", dest="end", type=date.fromisoformat, default=date(2026, 11, 16))
    args = p.parse_args(argv)

    if args.cmd == "list":
        for spec in sorted(REGISTRY.values(), key=lambda s: s.number):
            data = ", ".join(spec.data)
            print(f"{spec.number:>2}  {spec.key:<18} {spec.title}  (min {spec.min_days} d; {data})")
        if not REGISTRY:
            print("no patterns registered yet")
        return 0

    if args.cmd == "run":
        if args.key not in REGISTRY:
            print(f"unknown pattern {args.key!r}; try `list`", file=sys.stderr)
            return 2
        lo, hi = _window(args.data_dir, args.start, args.end, args.days)
        ctx = Context(args.data_dir, _item_ids(args.data_dir, args.group), lo, hi)
        res = run(args.key, ctx)
        print(f"{res.title}\n{res.basis_line()}\n{res.method}\n")
        if res.ready:
            _print_frame(res.ranked, args.top)
            if args.csv:
                res.ranked.to_csv(args.csv, index=False)
                print(f"\nwrote {args.csv}")
        return 0

    if args.cmd == "baseline":
        from coppertrail.patterns.baseline import baseline, format_baseline

        print(format_baseline(baseline(args.data_dir, args.start, args.end)))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
