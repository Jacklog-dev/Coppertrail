"""Everything the web front end needs, as JSON-able dicts. No Qt, no pywebview.

The app exposes this class to JS through pywebview's `js_api`; `--dev` and `--screenshot`
serve it over a 127.0.0.1 HTTP server (`devserver.py`). Display strings are formatted here
(`format.py`), so JS only lays them out.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from coppertrail.query.catalog import (
    ArchiveStatus,
    Item,
    archive_status,
    default_data_dir,
    load_items,
)
from coppertrail.query.filtering import apply_filters, date_window, item_classes
from coppertrail.query.groups import ItemGroup, load_groups, save_groups
from coppertrail.query.settings import Filters, load_settings, save_settings
from coppertrail.ui import format as fmt
from coppertrail.ui.pull import NOT_A_CLONE, can_pull, run_pull

AHLEDGER_URL = "https://ahledger.com"
STALE_AFTER_DAYS = 2
PREVIEW_ROWS = 300
SEARCH_ROWS = 50


def plural(n: int, word: str) -> str:
    return f"{fmt.thousands(n)} {word}{'' if n == 1 else 's'}"


def coin(copper: int | None) -> dict | None:
    if copper is None:
        return None
    return {"parts": [[n, u] for n, u in fmt.coin_parts(copper)], "text": fmt.coins_text(copper)}


def item_row(item: Item) -> dict:
    return {
        "id": item.item_id,
        "name": item.name,
        "class": item.item_class,
        "price": coin(item.min_buyout),
        "salesPerDay": fmt.count(item.sales_per_day),
    }


def group_to_dict(g: ItemGroup) -> dict:
    return {
        "name": g.name,
        "itemIds": list(g.item_ids),
        "patterns": list(g.patterns),
        "excludedIds": list(g.excluded_ids),
    }


def group_from_dict(d: dict) -> ItemGroup:
    """Extra keys (such as `count` from `state()`) are ignored."""
    return ItemGroup(
        name=str(d["name"]).strip(),
        item_ids=[int(i) for i in d.get("itemIds", [])],
        patterns=[str(p) for p in d.get("patterns", [])],
        excluded_ids=[int(i) for i in d.get("excludedIds", [])],
    )


def _iso(d) -> str | None:
    return d.isoformat() if d else None


class Bridge:
    EXPOSED: ClassVar[tuple[str, ...]] = (
        "state",
        "set_filters",
        "reset_filters",
        "save_groups",
        "group_members",
        "search_items",
        "match_names",
        "set_data_dir",
        "pull_latest",
    )

    def __init__(
        self, data_dir: Path | None = None, *, now: Callable[[], datetime] | None = None
    ) -> None:
        # `data_dir` is a session override (`--data-dir`): it is never written to settings.
        self._now = now or (lambda: datetime.now(UTC))
        self._settings = load_settings()
        if data_dir is not None:
            self.data_dir = Path(data_dir)
        elif self._settings.data_dir:
            self.data_dir = Path(self._settings.data_dir)
        else:
            self.data_dir = default_data_dir()
        self.groups: list[ItemGroup] = load_groups()
        self._load()

    # Loading -----------------------------------------------------------------

    def _load(self) -> None:
        try:
            self.items: list[Item] = load_items(self.data_dir)
            self.status: ArchiveStatus = archive_status(self.data_dir)
        except OSError:
            self.items, self.status = [], ArchiveStatus(None, None, None)

    @property
    def filters(self) -> Filters:
        return self._settings.filters

    def _save_filters(self, filters: Filters) -> None:
        self._settings.filters = filters
        save_settings(self._settings)

    # State -------------------------------------------------------------------

    def _status(self) -> dict:
        st = self.status
        age = st.age_days(self._now())
        stale = age is not None and age > STALE_AFTER_DAYS
        if st.as_of is None:
            text = "No data yet"
        elif stale:
            text = f"Data is {int(age)} days old · as of {fmt.local_datetime(st.as_of)}"
        else:
            text = f"Data as of {fmt.local_datetime(st.as_of)}"
        pullable = can_pull(self.data_dir)
        return {
            "text": text,
            "stale": stale,
            "empty": st.empty,
            "canPull": pullable,
            "pullHint": "" if pullable else NOT_A_CLONE,
        }

    def state(self) -> dict:
        f = self.filters
        shown = apply_filters(self.items, self.groups, f)
        lo, hi = date_window(f, self.status, today=self._now().date())
        active = f.active()
        names = {g.name for g in self.groups}
        selected = [g for g in self.groups if g.name in set(f.groups)]
        in_groups = (
            sum(1 for i in self.items if any(g.matches(i) for g in selected))
            if selected
            else len(self.items)
        )
        return {
            "dataDir": str(self.data_dir),
            "status": self._status(),
            "creditUrl": AHLEDGER_URL,
            "filters": f.to_json(),
            "active": active,
            "activeLabel": (f"{plural(len(active), 'filter')} active" if active else "No filters"),
            "classes": item_classes(self.items),
            "groups": [
                {**group_to_dict(g), "count": len(g.members(self.items))} for g in self.groups
            ],
            "groupsLabel": ", ".join(n for n in f.groups if n in names) or "All groups",
            "groupsSummary": (
                f"{len(selected)} of {len(self.groups)} selected · {plural(in_groups, 'item')}"
            ),
            "minSalesPass": (
                f"{fmt.thousands(len(shown))} of {plural(len(self.items), 'item')} pass"
            ),
            "window": {
                "from": lo.isoformat(),
                "to": hi.isoformat(),
                "label": fmt.date_range(lo, hi),
                "archiveFrom": _iso(self.status.first_day),
                "archiveTo": _iso(self.status.last_day),
            },
            "items": {
                "shown": len(shown),
                "total": len(self.items),
                "sub": f"{fmt.thousands(len(shown))} of {plural(len(self.items), 'item')}",
                "rows": [item_row(i) for i in shown[:PREVIEW_ROWS]],
            },
        }

    # Filters -----------------------------------------------------------------

    def set_filters(self, filters: dict[str, Any]) -> dict:
        """Merge the changed keys (Filters field names) into the current filters."""
        self._save_filters(Filters.from_json({**self.filters.to_json(), **filters}))
        return self.state()

    def reset_filters(self) -> dict:
        self._save_filters(Filters())
        return self.state()

    # Groups ------------------------------------------------------------------

    def save_groups(self, groups: list[dict], renamed: dict[str, str] | None = None) -> dict:
        """Replace all groups. The filter selection follows renames and drops deleted groups."""
        self.groups = [group_from_dict(g) for g in groups]
        save_groups(self.groups)
        renamed = renamed or {}
        names = {g.name for g in self.groups}
        selection: list[str] = []
        for name in self.filters.groups:
            name = renamed.get(name, name)
            if name in names and name not in selection:
                selection.append(name)
        if selection != self.filters.groups:
            self.filters.groups = selection
            self._save_filters(self.filters)
        return self.state()

    def group_members(self, group: dict) -> list[dict]:
        g = group_from_dict(group)
        return [item_row(i) for i in sorted(g.members(self.items), key=lambda i: i.name.casefold())]

    def search_items(self, text: str, group: dict) -> dict:
        """Items whose name contains `text` and that are not in `group` yet."""
        g = group_from_dict(group)
        needle = text.strip().casefold()
        hits = (
            [i for i in self.items if needle in i.name.casefold() and not g.matches(i)]
            if needle
            else []
        )
        hits.sort(key=lambda i: i.name.casefold())
        return {
            "rows": [item_row(i) for i in hits[:SEARCH_ROWS]],
            "note": f"{plural(len(hits), 'result')} not yet in group",
        }

    def match_names(self, names: list[str]) -> dict:
        """Exact, case-insensitive name matches for a pasted list (one name per line)."""
        by_name = {i.name.casefold(): i.item_id for i in self.items}
        wanted = [n.strip() for n in names if n.strip()]
        ids: list[int] = []
        missing = 0
        for name in wanted:
            item_id = by_name.get(name.casefold())
            if item_id is None:
                missing += 1
            elif item_id not in ids:
                ids.append(item_id)
        note = f"{plural(missing, 'pasted name')} not found" if missing else ""
        return {"ids": ids, "missing": missing, "note": note}

    # Data folder and pull ----------------------------------------------------

    def set_data_dir(self, path: str) -> dict:
        self.data_dir = Path(path)
        self._settings.data_dir = str(self.data_dir)
        save_settings(self._settings)
        self._load()
        return self.state()

    def pull_latest(self) -> dict:
        result = run_pull(self.data_dir)
        if result.ok:
            self._load()
        return asdict(result)
