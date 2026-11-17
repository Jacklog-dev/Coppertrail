"""Everything the web front end needs, as JSON-able dicts. No Qt, no pywebview.

The app exposes this class to JS through pywebview's `js_api`; `--dev` and `--screenshot`
serve it over a 127.0.0.1 HTTP server (`devserver.py`). Display strings are formatted here
(`format.py`), so JS only lays them out.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
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
from coppertrail.ui.pull import COMMAND, NO_GIT, NOT_A_CLONE, PullResult, can_pull, run_pull

AHLEDGER_URL = "https://ahledger.com"
STALE_AFTER_DAYS = 2
PREVIEW_ROWS = 300
UNREADABLE = "Could not read this data folder"
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


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _git_cause(result: PullResult) -> str:
    """One sentence on why the pull failed, from git's own last complaint."""
    if result.message == NO_GIT:
        return _sentence(
            f"git could not be started: {result.detail}"
            if result.detail
            else "git could not be started"
        )
    lines = [ln.strip() for ln in result.detail.splitlines()]
    for line in reversed(lines):
        for prefix in ("fatal:", "error:"):
            if line.lower().startswith(prefix):
                return _sentence(f"git stopped: {line[len(prefix) :].strip()}")
    if result.message.startswith("Pull failed"):
        return "git pull did not finish."
    return _sentence(result.message)


def pull_failure(result: PullResult, *, as_of: datetime | None, at: datetime) -> dict:
    """The "Pull failed" state (HANDOVER 8b States): cause, reassurance, request line, log."""
    if as_of is None:
        reassurance = "Nothing in the data folder was changed."
    else:
        reassurance = (
            "Your local archive is unchanged — everything up to "
            f"{fmt.short_datetime(as_of)} is still here."
        )
    request = [COMMAND]
    if result.returncode is not None:
        request.append(f"exit {result.returncode}")
    request.append(fmt.clock(at))
    return {
        "title": "Pull failed",
        "cause": _git_cause(result),
        "reassurance": reassurance,
        "request": " · ".join(request),
        "log": result.detail or "git printed nothing.",
    }


def history_gap(
    name: str,
    *,
    needed: int,
    have: int,
    ready_on: date | None,
    unit: str = "day",
    missing_days: int | None = None,
) -> dict:
    """The "Too little history" state for a pattern tab.

    `needed`/`have` count `unit`s (days, resets, weekends); `missing_days` is how many days
    of data are still missing (defaults to `needed - have` for days).
    """
    missing = missing_days if missing_days is not None else max(0, needed - have)
    return {
        "title": fmt.needs_more(missing),
        "why": (
            f"“{name}” needs {plural(needed, unit)} of history. The archive covers "
            f"{fmt.thousands(have)} so far — too few to separate a pattern from noise."
        ),
        "progress": f"{fmt.thousands(have)} of {plural(needed, unit)}",
        "ready": f"ready around {fmt.day(ready_on)}" if ready_on else "",
        "pct": round(100 * min(1.0, have / needed), 1) if needed else 100.0,
    }


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
        # Held by every JS call (app facade, dev server) and by the pull worker's reload.
        self.lock = threading.RLock()
        self.load_error = ""
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
        # Any failure (unreadable or foreign parquet, DuckDB errors) leaves an empty archive
        # and an error in the status strip; it must never stop the app from opening.
        try:
            items, status = load_items(self.data_dir), archive_status(self.data_dir)
            error = ""
        except Exception as exc:  # noqa: BLE001
            items, status, error = (
                [],
                ArchiveStatus(None, None, None),
                f"{type(exc).__name__}: {exc}",
            )
        self.items: list[Item] = items
        self.status: ArchiveStatus = status
        self.load_error = error

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
        if self.load_error:
            text = UNREADABLE
        elif st.as_of is None:
            text = "No data yet"
        elif stale:
            text = f"Data is {int(age)} days old · as of {fmt.local_datetime(st.as_of)}"
        else:
            text = f"Data as of {fmt.local_datetime(st.as_of)}"
        pullable = can_pull(self.data_dir)
        as_of = st.as_of
        return {
            "text": text,
            "stale": stale,
            "ageDays": None if age is None else int(age),
            "lastPoint": int(as_of.timestamp()) if as_of else None,
            "now": int(self._now().timestamp()),
            "noDataSince": (
                f"no data since {fmt.short_datetime(as_of).replace(',', '')}" if as_of else ""
            ),
            "banner": (
                {
                    "title": f"Data is {int(age)} days old.",
                    "detail": f"Charts end on {fmt.short_datetime(as_of)}.",
                }
                if stale and not self.load_error
                else None
            ),
            "error": bool(self.load_error),
            "errorDetail": self.load_error,
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
            "noMatch": self._no_match(shown),
            "items": {
                "shown": len(shown),
                "total": len(self.items),
                "sub": f"{fmt.thousands(len(shown))} of {plural(len(self.items), 'item')}",
                "rows": [item_row(i) for i in shown[:PREVIEW_ROWS]],
            },
        }

    def _no_match(self, shown: list[Item]) -> dict | None:
        """Chips per active item filter and the single filter whose removal helps most.

        The date range never drops items, so it gets no chip.
        """
        if shown or not self.items:
            return None
        f = self.filters
        names = {g.name for g in self.groups}
        groups = [n for n in f.groups if n in names]
        chips: list[dict] = []
        if groups:
            label = "Group" if len(groups) == 1 else "Groups"
            chips.append({"label": f"{label}: {', '.join(groups)}", "clear": {"groups": []}})
        if f.item_class:
            chips.append({"label": f"Class: {f.item_class}", "clear": {"item_class": ""}})
        if f.search.strip():
            chips.append({"label": f"Search: “{f.search.strip()}”", "clear": {"search": ""}})
        if f.min_sales:
            chips.append(
                {
                    "label": f"Min sales/day ≥ {fmt.thousands(f.min_sales)}",
                    "clear": {"min_sales": 0},
                }
            )
        best: tuple[int, str] | None = None
        for chip in chips:
            relaxed = Filters.from_json({**f.to_json(), **chip["clear"]})
            n = len(apply_filters(self.items, self.groups, relaxed))
            if n and (best is None or n > best[0]):
                best = (n, chip["label"])
        hint = (
            {
                "prefix": "Closest: without",
                "label": best[1],
                "result": f"→ {plural(best[0], 'item')}",
            }
            if best
            else None
        )
        return {
            "sub": f"0 of {plural(len(self.items), 'item')} · remove one to widen the search",
            "chips": chips,
            "hint": hint,
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

    def pull_failure(self, result: PullResult) -> dict | None:
        if result.ok:
            return None
        return pull_failure(result, as_of=self.status.as_of, at=self._now())

    def pull_latest(self) -> dict:
        result = run_pull(self.data_dir)
        if result.ok:
            self._load()
        return {**asdict(result), "failure": self.pull_failure(result)}
