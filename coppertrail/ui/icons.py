"""Item icons: item id -> icon file id (shipped in `web/icon-map.json`) -> image URL.

The map is built once by `scripts/fetch_icon_map.py`. The images themselves are never stored;
the page loads them from Blizzard's render host, which needs no key.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

ICON_URL = "https://render.worldofwarcraft.com/eu/icons/56/{}.jpg"
ICON_HOST = "https://render.worldofwarcraft.com"


def map_path() -> Path:
    from coppertrail.ui.devserver import web_dir  # devserver imports the bridge

    return web_dir() / "icon-map.json"


def read_map(path: Path) -> dict[int, int]:
    """The map in `path`; empty when the file is missing or not a valid map."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {int(k): int(v) for k, v in raw.items() if int(k) > 0 and int(v) > 0}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


@cache
def load_map() -> dict[int, int]:
    return read_map(map_path())


def icon_url(item_id: int, m: dict[int, int] | None = None) -> str | None:
    file_id = (load_map() if m is None else m).get(int(item_id))
    return ICON_URL.format(file_id) if file_id else None
