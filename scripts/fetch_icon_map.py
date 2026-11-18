"""Build the item -> icon file id map the GUI ships: `coppertrail/ui/web/icon-map.json`.

    uv run python scripts/fetch_icon_map.py                 # items known in $COPPERTRAIL_DATA
    uv run python scripts/fetch_icon_map.py --data-dir DIR  # another data folder

Run it once, and again after a patch adds items, then release. It asks Blizzard's media
endpoint once per item that is not in the map yet (`--all` asks again for every item) and
keeps every entry it already has. Credentials as for the collector; they are never printed.
The images are not stored anywhere: the app loads them by URL (`coppertrail/ui/icons.py`).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "coppertrail" / "ui" / "web" / "icon-map.json"

log = logging.getLogger("fetch_icon_map")


def merge(old: dict[int, int], new: dict[int, int | None]) -> dict[int, int]:
    """`old` updated with every found entry of `new`; a failed lookup (None) drops nothing."""
    out = dict(old)
    out.update({k: v for k, v in new.items() if v})
    return out


def write_map(path: Path, m: dict[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {str(k): m[k] for k in sorted(m)}
    path.write_text(json.dumps(body, separators=(",", ":")) + "\n", encoding="utf-8")


def known_item_ids(data_dir: Path) -> list[int]:
    """Every item id in the copied item details and the hourly summaries."""
    import duckdb

    ids: set[int] = set()
    for pattern in ("window/blizzard/items/*.parquet", "hourly/*/*.parquet"):
        files = [f.as_posix() for f in sorted(data_dir.glob(pattern))]
        if files:
            rows = duckdb.execute(
                "SELECT DISTINCT item_id FROM read_parquet(?)", [files]
            ).fetchall()
            ids.update(int(r[0]) for r in rows)
    return sorted(ids)


def lookup(client, ids: Iterable[int]) -> dict[int, int | None]:
    ids = list(ids)
    out: dict[int, int | None] = {}
    for n, item_id in enumerate(ids, 1):
        out[item_id] = client.media_icon(item_id)
        if n % 250 == 0:
            log.info("%d of %d", n, len(ids))
    return out


def main(argv: list[str] | None = None) -> int:
    import os

    from coppertrail.collector.blizzard import BlizzardClient
    from coppertrail.collector.config import load_config
    from coppertrail.collector.credentials import load_credentials
    from coppertrail.ui.icons import read_map

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_dir = Path(os.environ.get("COPPERTRAIL_DATA", ROOT / "private"))
    p.add_argument("--data-dir", type=Path, default=default_dir)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--all", action="store_true", help="look up items already in the map too")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request otherwise

    data_dir = args.data_dir
    old = read_map(args.out)
    ids = known_item_ids(data_dir)
    todo = ids if args.all else [i for i in ids if i not in old]
    log.info("%d items known, %d in the map, %d to look up", len(ids), len(old), len(todo))
    if todo:
        cfg = load_config(data_dir)
        cid, secret = load_credentials()
        with BlizzardClient(cfg.blizzard, cid, secret) as client:
            found = lookup(client, todo)
            log.info("%d requests", client.requests)
        new = merge(old, found)
        missing = sum(1 for v in found.values() if not v)
        log.info("%d entries (%d without an icon)", len(new), missing)
        write_map(args.out, new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
