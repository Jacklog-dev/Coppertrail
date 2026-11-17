"""User settings: the data folder and the filters, remembered between sessions.

Lives in the user's config directory (never in the data repo):
Windows `%APPDATA%\\Coppertrail`, elsewhere `$XDG_CONFIG_HOME/coppertrail` or
`~/.config/coppertrail`. `$COPPERTRAIL_CONFIG` overrides it (tests use this).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path

SETTINGS_FILE = "settings.json"

RANGE_PRESETS = ("24h", "7d", "30d", "all")
DEFAULT_RANGE = "30d"
MIN_SALES_PRESETS = (0, 10, 50, 200, 1_000)


def config_dir() -> Path:
    if env := os.environ.get("COPPERTRAIL_CONFIG"):
        return Path(env)
    if sys.platform == "win32" and (appdata := os.environ.get("APPDATA")):
        return Path(appdata) / "Coppertrail"
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "coppertrail"


@dataclass
class Filters:
    """Filter bar state. Defaults mean "no filter"; every non-default value counts as active."""

    groups: list[str] = field(default_factory=list)  # selected group names; empty = all
    item_class: str = ""  # "" = all classes
    search: str = ""
    range: str = DEFAULT_RANGE  # one of RANGE_PRESETS, or "custom"
    date_from: date | None = None  # only for range == "custom"
    date_to: date | None = None
    min_sales: int = 0

    def active(self) -> list[str]:
        """Labels of the filters that differ from the defaults, in filter bar order."""
        out = []
        if self.groups:
            out.append("Groups")
        if self.item_class:
            out.append("Class")
        if self.search.strip():
            out.append("Search")
        if self.range != DEFAULT_RANGE:
            out.append("Date range")
        if self.min_sales:
            out.append("Min sales/day")
        return out

    def to_json(self) -> dict:
        d = asdict(self)
        for k in ("date_from", "date_to"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_json(cls, raw: dict) -> Filters:
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in raw.items() if k in names}
        for k in ("date_from", "date_to"):
            kw[k] = date.fromisoformat(kw[k]) if kw.get(k) else None
        f = cls(**kw)
        if f.range not in (*RANGE_PRESETS, "custom"):
            f.range = DEFAULT_RANGE
        if f.range == "custom" and not (f.date_from and f.date_to):
            f.range = DEFAULT_RANGE
        f.groups = [str(g) for g in f.groups]
        f.min_sales = max(0, int(f.min_sales))
        return f


@dataclass
class Settings:
    data_dir: str = ""  # "" = default ($COPPERTRAIL_DATA or ./private)
    filters: Filters = field(default_factory=Filters)


def settings_path(directory: Path | None = None) -> Path:
    return (directory or config_dir()) / SETTINGS_FILE


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Settings(
            data_dir=str(raw.get("data_dir") or ""),
            filters=Filters.from_json(raw.get("filters") or {}),
        )
    except (OSError, ValueError, TypeError):
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {"version": 1, "data_dir": settings.data_dir, "filters": settings.filters.to_json()},
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)
