"""Collector settings: the Blizzard house, the item selection and the retention rules.

Defaults live here; `<data-dir>/collector.toml` overrides them per table
(`[blizzard]`, `[selection]`, `[retention]`). Unknown tables or keys are an error,
so a typo never silently falls back to a default.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

QUALITY_ORDER: tuple[str, ...] = (
    "POOR",
    "COMMON",
    "UNCOMMON",
    "RARE",
    "EPIC",
    "LEGENDARY",
    "ARTIFACT",
    "HEIRLOOM",
)


@dataclass(frozen=True)
class Blizzard:
    region: str = "eu"
    ruleset: int = 2
    house: int = 111
    expect_house_name: str = "Alliance"
    locale: str = "en_GB"
    rate_per_s: float = 20.0
    timeout_s: float = 60.0
    max_retries: int = 4


@dataclass(frozen=True)
class Selection:
    exclude_qualities: tuple[str, ...] = ("POOR",)
    min_median: dict[str, int] = field(default_factory=lambda: {"COMMON": 50})
    exclude_classes: tuple[str, ...] = ("Recipe",)
    equipment_classes: tuple[str, ...] = ("Armor", "Weapon")
    equipment_min_quality: str = "EPIC"
    include_unclassified: bool = True
    max_items: int = 2000
    rank_days: int = 7
    keep_rank: int = 2200


@dataclass(frozen=True)
class Retention:
    copied_days: int = 30
    summary_retention_days: int = 0  # 0 = keep hourly summaries for good


@dataclass(frozen=True)
class Config:
    blizzard: Blizzard
    selection: Selection
    retention: Retention
    data_dir: Path
    window_dir: Path
    state_dir: Path


_SECTIONS = {"blizzard": Blizzard, "selection": Selection, "retention": Retention}


def _section(cls, raw: dict, name: str):
    known = {f.name: f for f in fields(cls)}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ValueError(f"collector.toml [{name}]: unknown key(s) {', '.join(unknown)}")
    values = {}
    for key, value in raw.items():
        default = getattr(cls(), key)
        if isinstance(default, tuple):
            value = tuple(value)
        elif isinstance(default, dict):
            value = {str(k): int(v) for k, v in value.items()}
        values[key] = value
    return replace(cls(), **values)


def _check_qualities(sel: Selection) -> None:
    named = [*sel.exclude_qualities, *sel.min_median, sel.equipment_min_quality]
    bad = [q for q in named if q not in QUALITY_ORDER]
    if bad:
        raise ValueError(f"collector.toml [selection]: unknown quality {', '.join(bad)}")


def load_config(data_dir: Path) -> Config:
    data_dir = Path(data_dir)
    raw: dict = {}
    path = data_dir / "collector.toml"
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = sorted(set(raw) - set(_SECTIONS))
    if unknown:
        raise ValueError(f"collector.toml: unknown table(s) {', '.join(unknown)}")
    parts = {name: _section(cls, raw.get(name, {}), name) for name, cls in _SECTIONS.items()}
    _check_qualities(parts["selection"])
    return Config(
        **parts,
        data_dir=data_dir,
        window_dir=data_dir / "window",
        state_dir=data_dir / ".state",
    )
