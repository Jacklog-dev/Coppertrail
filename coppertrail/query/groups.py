"""User-defined item groups (HANDOVER 8a): a name plus item ids and/or name patterns.

Stored as JSON in the user's config directory, not in the data repo. Patterns are
case-insensitive shell globs (`* Leather`, `Cured * Hide`) matched against item names,
so starter groups work without knowing item ids.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

from coppertrail.query.catalog import Item
from coppertrail.query.settings import config_dir

GROUPS_FILE = "groups.json"


@dataclass
class ItemGroup:
    name: str
    item_ids: list[int] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    excluded_ids: list[int] = field(default_factory=list)  # removed although a pattern matches

    def matches(self, item: Item) -> bool:
        if item.item_id in self.excluded_ids:
            return False
        if item.item_id in self.item_ids:
            return True
        name = item.name.casefold()
        return any(fnmatchcase(name, p.casefold()) for p in self.patterns)

    def members(self, items: Iterable[Item]) -> list[Item]:
        return [i for i in items if self.matches(i)]

    def add(self, item_id: int) -> None:
        if item_id in self.excluded_ids:
            self.excluded_ids.remove(item_id)
        if item_id not in self.item_ids:
            self.item_ids.append(item_id)

    def remove(self, item_id: int) -> None:
        if item_id in self.item_ids:
            self.item_ids.remove(item_id)
        if item_id not in self.excluded_ids:
            self.excluded_ids.append(item_id)  # keeps a pattern from adding it back


HERBS = [
    "Peacebloom",
    "Silverleaf",
    "Earthroot",
    "Mageroyal",
    "Briarthorn",
    "Swiftthistle",
    "Stranglekelp",
    "Bruiseweed",
    "Wild Steelbloom",
    "Grave Moss",
    "Kingsblood",
    "Liferoot",
    "Fadeleaf",
    "Goldthorn",
    "Khadgar's Whisker",
    "Wintersbite",
    "Firebloom",
    "Purple Lotus",
    "Arthas' Tears",
    "Sungrass",
    "Blindweed",
    "Ghost Mushroom",
    "Gromsblood",
    "Golden Sansam",
    "Dreamfoil",
    "Mountain Silversage",
    "Plaguebloom",
    "Icecap",
    "Black Lotus",
]

SCARCE = [
    "Black Lotus",
    "Arcane Crystal",
    "Arcanite Bar",
    "Mooncloth",
    "Large Brilliant Shard",
    "Essence of Undeath",
    "Essence of Fire",
    "Essence of Earth",
    "Essence of Water",
    "Essence of Air",
    "Living Essence",
    "Righteous Orb",
    "Devilsaur Leather",
    "Enchanted Leather",
]


def starter_groups() -> list[ItemGroup]:
    """The groups shipped on first start (HANDOVER 8a). Users edit them freely."""
    return [
        ItemGroup(
            "Leather chain",
            patterns=[
                "* Leather",
                "* Hide",
                "* Armor Kit",
                "Cured * Hide",
                "Light Leather",
            ],
        ),
        ItemGroup(
            "Cloth",
            patterns=[
                "Linen Cloth",
                "Wool Cloth",
                "Silk Cloth",
                "Mageweave Cloth",
                "Runecloth",
                "Felcloth",
                "Mooncloth",
                "Bolt of *",
            ],
        ),
        ItemGroup(
            "Ore and bars",
            patterns=[
                "* Ore",
                "* Bar",
                "Rough Stone",
                "Coarse Stone",
                "Heavy Stone",
                "Solid Stone",
                "Dense Stone",
            ],
        ),
        ItemGroup("Herbs", patterns=list(HERBS)),
        ItemGroup(
            "Enchanting",
            patterns=[
                "* Dust",
                "* Magic Essence",
                "* Astral Essence",
                "* Mystic Essence",
                "* Nether Essence",
                "* Eternal Essence",
                "* Glimmering Shard",
                "* Glowing Shard",
                "* Radiant Shard",
                "* Brilliant Shard",
                "Nexus Crystal",
            ],
        ),
        ItemGroup("Scarce goods", patterns=list(SCARCE)),
    ]


def groups_path(directory: Path | None = None) -> Path:
    return (directory or config_dir()) / GROUPS_FILE


def load_groups(path: Path | None = None) -> list[ItemGroup]:
    """Saved groups, or the starter groups when nothing is saved yet (or the file is broken)."""
    path = path or groups_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [
            ItemGroup(
                name=str(g["name"]),
                item_ids=[int(i) for i in g.get("item_ids", [])],
                patterns=[str(p) for p in g.get("patterns", [])],
                excluded_ids=[int(i) for i in g.get("excluded_ids", [])],
            )
            for g in raw["groups"]
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return starter_groups()


def save_groups(groups: list[ItemGroup], path: Path | None = None) -> None:
    path = path or groups_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "groups": [asdict(g) for g in groups]}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)
