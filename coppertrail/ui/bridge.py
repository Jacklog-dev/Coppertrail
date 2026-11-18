"""Everything the web front end needs, as JSON-able dicts. No Qt, no pywebview.

The app exposes this class to JS through pywebview's `js_api`; `--dev` and `--screenshot`
serve it over a 127.0.0.1 HTTP server (`devserver.py`). Display strings are formatted here
(`format.py`), so JS only lays them out.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from concurrent.futures import Future
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from coppertrail.patterns import REGISTRY, Context, PatternResult
from coppertrail.patterns import run as run_pattern
from coppertrail.patterns.inflation import classify
from coppertrail.query import series
from coppertrail.query.catalog import (
    ArchiveStatus,
    Item,
    archive_status,
    default_data_dir,
    load_items,
)
from coppertrail.query.filtering import RANGE_DAYS, apply_filters, date_window, item_classes
from coppertrail.query.groups import ItemGroup, load_groups, save_groups
from coppertrail.query.settings import Filters, load_settings, save_settings
from coppertrail.ui import format as fmt
from coppertrail.ui import movers as mv
from coppertrail.ui import patternview as pv
from coppertrail.ui import viewdata as vd
from coppertrail.ui.pull import (
    COMMAND,
    DOWNLOAD_FAILED,
    NO_GH,
    NO_GIT,
    NOT_A_CLONE,
    PullResult,
    can_pull,
    run_pull,
)
from coppertrail.ui.viewdata import coin, plural

STALE_AFTER_DAYS = 2
PREVIEW_ROWS = 300
UNREADABLE = "Could not read this data folder"
SEARCH_ROWS = 50
LIST_ROWS = 500  # Item detail list panel
WEEK_READ_DAYS = 9  # hourly read for the "7 d" figures: a week plus partial edge days
EVENT_JOBS = ("mispricings", "supply_shocks", "buyouts")


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
    if result.message == NO_GH:
        return (
            "The GitHub CLI (gh) could not be started: install it and sign in with gh auth login."
        )
    lines = [ln.strip() for ln in result.detail.splitlines() if ln.strip()]
    if result.message == DOWNLOAD_FAILED:
        why = f": {lines[-1]}" if lines else ""
        return _sentence(f"The item data could not be downloaded{why}")
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
    request = [
        "gh api … actions/artifacts" if result.message in (NO_GH, DOWNLOAD_FAILED) else COMMAND
    ]
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
    if missing_days is None:
        if unit != "day":
            raise ValueError("missing_days is required when unit is not 'day'")
        missing_days = max(0, needed - have)
    missing = missing_days
    return {
        "title": fmt.needs_more(missing),
        "why": (
            f"“{name}” needs {plural(needed, unit)} of history. The archive covers "
            f"{plural(have, unit)} so far — too few to separate a pattern from noise."
        ),
        "progress": f"{fmt.thousands(have)} of {plural(needed, unit)}",
        "ready": f"ready around {fmt.day(ready_on)}" if ready_on else "",
        "pct": round(100 * min(1.0, have / needed), 1) if needed else 100.0,
    }


def window_gap(name: str, *, needed: int, have: int) -> dict:
    """The archive is long enough, but the selected date range is shorter than `needed` days.

    Same shape as `history_gap`, without a ready date: widening the range fixes it now.
    """
    wider = [d for d in RANGE_DAYS.values() if d >= needed]
    target = f"{min(wider)} d or All" if wider else "All"
    return {
        "title": f"Needs at least {plural(needed, 'day')}",
        "why": (
            f"“{name}” needs at least {plural(needed, 'day')} of history, but the date range "
            f"covers {plural(have, 'day')}: widen the date range to {target}."
        ),
        "progress": f"{fmt.thousands(have)} of {plural(needed, 'day')}",
        "ready": "",
        "pct": round(100 * min(1.0, have / needed), 1) if needed else 100.0,
    }


def pattern_gap(
    name: str, *, needed: int, window_days: int, archive_days: int, last_day: date | None
) -> dict:
    """Too little history: in the archive (with a ready date) or only in the date range."""
    if archive_days >= needed:
        return window_gap(name, needed=needed, have=window_days)
    missing = needed - archive_days
    return history_gap(
        name,
        needed=needed,
        have=archive_days,
        ready_on=last_day + timedelta(days=missing) if last_day else None,
    )


def archive_days(status: ArchiveStatus) -> int:
    """Days the archive spans (first to last hourly day), 0 without data."""
    if status.first_day is None or status.last_day is None:
        return 0
    return (status.last_day - status.first_day).days + 1


class Memo:
    """A small LRU of futures: concurrent callers of one key wait for a single computation.

    A failed computation is not kept, so the next call tries again. `clear()` starts a new
    generation: a computation that read its inputs in an older one (it began before a pull)
    still returns its result, but the result is not kept, so it cannot outlive the reload.
    """

    def __init__(self, size: int = 128) -> None:
        self._lock = threading.Lock()
        self._futures: OrderedDict[Hashable, Future] = OrderedDict()
        self._size = size
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def get(self, key: Hashable, compute: Callable[[], Any], generation: int | None = None) -> Any:
        """`generation`: the one the caller's inputs were read in (default: the current)."""
        with self._lock:
            gen = self._generation if generation is None else generation
            if gen != self._generation:
                stale = True
            else:
                stale = False
                fut = self._futures.get(key)
                owner = fut is None
                if owner:
                    fut = self._futures[key] = Future()
                    while len(self._futures) > self._size:
                        self._futures.popitem(last=False)
                else:
                    self._futures.move_to_end(key)
        if stale:
            return compute()  # inputs from before the last clear(): never cached
        if owner:
            try:
                fut.set_result(compute())
            except BaseException as exc:
                fut.set_exception(exc)
                with self._lock:
                    if self._futures.get(key) is fut:
                        del self._futures[key]
            else:
                with self._lock:
                    # Cleared while computing: drop it if a newer caller has not replaced it.
                    if self._generation != gen and self._futures.get(key) is fut:
                        del self._futures[key]
        return fut.result()

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._futures.clear()


def item_details(data_dir: Path) -> dict[int, dict]:
    """item_id -> {subclass, vendor_price}: the newest non-null value of each (thin helper).
    Items without either give no entry."""
    out = {}
    for r in series.item_details(data_dir).itertuples(index=False):
        d = {
            "subclass": r.subclass if isinstance(r.subclass, str) else None,
            "vendor_price": None if pd.isna(r.vendor_price) else int(r.vendor_price),
        }
        if any(v is not None for v in d.values()):
            out[int(r.item_id)] = d
    return out


@dataclass(frozen=True)
class ViewInputs:
    """What a view method reads, copied under the bridge lock (then computed without it)."""

    data_dir: Path
    status: ArchiveStatus
    items: list[Item]
    shown: list[Item]
    groups: list[ItemGroup]
    lo: date
    hi: date
    generation: int = 0  # Memo generation the inputs were read in (see Memo.clear)

    @property
    def ids(self) -> list[int] | None:
        """The filtered item ids; None when nothing is filtered out (cheaper reads)."""
        return None if len(self.shown) == len(self.items) else [i.item_id for i in self.shown]

    @property
    def key(self) -> tuple:
        ids = self.ids
        return (
            str(self.data_dir),
            self.status.as_of,
            self.lo,
            self.hi,
            None if ids is None else tuple(sorted(ids)),
            tuple(
                (g.name, tuple(g.item_ids), tuple(g.patterns), tuple(g.excluded_ids))
                for g in self.groups
            ),
        )


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
        "overview",
        "overview_events",
        "item_list",
        "item_detail",
        "add_to_group",
        "patterns",
        "movers",
        "mispricings_now",
    )
    # Called without the bridge lock (js_facade, dev server): they copy their inputs under
    # it and run the slow part (pattern jobs) unlocked, so the filter bar stays responsive.
    UNLOCKED: ClassVar[tuple[str, ...]] = (
        "overview",
        "overview_events",
        "item_list",
        "item_detail",
        "patterns",
        "movers",
        "mispricings_now",
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
        self.memo = Memo()
        self._load()

    # Loading -----------------------------------------------------------------

    def _load(self) -> None:
        # Any failure (unreadable or foreign parquet, DuckDB errors) leaves an empty archive
        # and an error in the status strip; it must never stop the app from opening.
        try:
            items = load_items(self.data_dir)
            status = archive_status(self.data_dir, now=self._now())
            error = ""
        except Exception as exc:  # noqa: BLE001
            items, status, error = (
                [],
                ArchiveStatus(None, None),
                f"{type(exc).__name__}: {exc}",
            )
        self.items: list[Item] = items
        self.status: ArchiveStatus = status
        self.load_error = error
        self.memo.clear()  # a pull may add rows without a newer as_of

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
            # Changes on every load (pull, folder change): part of the page's view keys, so
            # the views ask again even when a pull added rows without a newer as_of.
            "generation": self.memo.generation,
            "status": self._status(),
            "creditText": fmt.CREDIT_TEXT,
            "creditUrl": fmt.CREDIT_URL,
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

    # Views (Market overview, Item detail) ---------------------------------------------
    # Spec: docs/superpowers/specs/2026-11-17-market-item-views.md

    def _inputs(self) -> ViewInputs:
        with self.lock:
            f = self.filters
            lo, hi = date_window(f, self.status, today=self._now().date())
            return ViewInputs(
                data_dir=self.data_dir,
                status=self.status,
                items=self.items,
                shown=apply_filters(self.items, self.groups, f),
                groups=[group_from_dict(group_to_dict(g)) for g in self.groups],
                lo=lo,
                hi=hi,
                generation=self.memo.generation,
            )

    def _memo(self, inp: ViewInputs, key: Hashable, compute: Callable[[], Any]) -> Any:
        """Memo.get in the generation `inp` was read in: a pull meanwhile keeps it uncached."""
        return self.memo.get(key, compute, inp.generation)

    def _week(self, inp: ViewInputs) -> pd.DataFrame:
        """The daily table over the archive's last days, all items (every "7 d" figure)."""

        def compute() -> pd.DataFrame:
            last = inp.status.last_day
            if last is None:
                return vd.daily_table(pd.DataFrame())
            first = last - timedelta(days=WEEK_READ_DAYS)
            return vd.daily_table(series.hourly(inp.data_dir, None, first, last))

        return self._memo(inp, ("week", str(inp.data_dir), inp.status.as_of), compute)

    def _house(self, inp: ViewInputs) -> pd.DataFrame:
        """Whole-house totals per CET day (from one house row per snapshot)."""
        return self._memo(
            inp,
            ("house", str(inp.data_dir), inp.status.as_of),
            lambda: vd.house_daily(series.house(inp.data_dir)),
        )

    def _details(self, inp: ViewInputs) -> dict[int, dict]:
        return self._memo(
            inp,
            ("details", str(inp.data_dir), inp.status.as_of),
            lambda: item_details(inp.data_dir),
        )

    def overview(self) -> dict:
        """Market overview without "What changed" (that is `overview_events`, slower)."""
        inp = self._inputs()
        return self._memo(inp, ("overview", *inp.key), lambda: self._overview(inp))

    def _overview(self, inp: ViewInputs) -> dict:
        lo, hi = inp.lo, inp.hi
        sub = f"{fmt.thousands(len(inp.shown))} of {plural(len(inp.items), 'item')}"
        if not inp.shown:
            return {"sub": sub}
        ctx = Context(inp.data_dir, inp.ids, lo, hi)  # shared by the jobs below
        week = self._week(inp)
        week_shown = week[week["item_id"].isin({i.item_id for i in inp.shown})]
        frame = pd.DataFrame(
            {"item_id": [i.item_id for i in inp.shown], "name": [i.name for i in inp.shown]}
        )
        house = self._house(inp)
        out: dict[str, Any] = {"sub": sub}

        def section(name: str, build: Callable[[], Any]) -> None:
            # One failing job must not take the whole view down: that card shows the error.
            try:
                out[name] = build()
            except Exception as exc:  # noqa: BLE001
                out[name] = {"sub": vd.range_sub(lo, hi), "note": _failed(exc)}

        inflation: PatternResult | None = None
        try:
            inflation = run_pattern("inflation", ctx)
        except Exception as exc:  # noqa: BLE001
            out["index"] = {"sub": vd.range_sub(lo, hi), "note": _failed(exc)}
        else:
            section("index", lambda: vd.index_chart(inflation, lo, hi))
        section(
            "tiles",
            lambda: vd.overview_tiles(
                total=len(inp.items),
                shown=len(inp.shown),
                daily=week_shown,
                classes=classify(frame),
                inflation=inflation,
                house=house,
            ),
        )
        section("rhythm", lambda: self._rhythm(inp, ctx))
        section("supply", lambda: vd.supply_chart(ctx.hourly, lo, hi, vd.week_supply(week_shown)))
        section("gold", lambda: vd.gold_chart(house, lo, hi))
        return out

    def _rhythm(self, inp: ViewInputs, ctx: Context) -> dict:
        result = run_pattern("daily_rhythm", ctx)
        gap = None
        if not result.ready:
            gap = pattern_gap(
                result.title,
                needed=REGISTRY["daily_rhythm"].min_days,
                window_days=result.days_used,
                archive_days=archive_days(inp.status),
                last_day=inp.status.last_day or inp.hi,
            )
        out = vd.rhythm_chart(result, inp.lo, inp.hi, gap)
        shown = {i.item_id for i in inp.shown}
        members = [(g.name, {i.item_id for i in g.members(inp.items)} & shown) for g in inp.groups]
        out["groups"] = vd.rhythm_by_group(result, members, inp.lo, inp.hi)
        return out

    def overview_events(self) -> dict:
        """What changed: events of the last 7 archive days for the filtered items."""
        inp = self._inputs()
        return self._memo(inp, ("events", *inp.key), lambda: self._overview_events(inp))

    def _overview_events(self, inp: ViewInputs) -> dict:
        last = inp.status.last_day
        if last is None or not inp.shown:
            return {"sub": "", "rows": [], "note": "No data yet."}
        lo = max(last - timedelta(days=vd.WEEK - 1), inp.status.first_day or last)
        ctx = Context(inp.data_dir, inp.ids, lo, last)
        results, failed = [], []
        for key in EVENT_JOBS:
            try:
                results.append(run_pattern(key, ctx))
            except Exception:  # noqa: BLE001 - the other jobs' events still show
                failed.append(key)
        names = {i.item_id: i.name for i in inp.items}
        sales = {i.item_id: i.sales_per_day for i in inp.items}
        out = vd.what_changed(results, names, sales, lo, last)
        if failed:
            out["failed"] = f"Could not compute: {', '.join(failed)}"
        return out

    def item_list(self, sort: str = "sales", pin: int | None = None) -> dict:
        """The filtered items, sorted; `pin` (the shown item) is kept even beyond the limit."""
        inp = self._inputs()
        pin = None if pin is None else int(pin)

        def compute() -> dict:
            changes = vd.week_change(self._week(inp))
            return vd.item_list(inp.shown, changes, self._details(inp), sort, LIST_ROWS, pin)

        return self._memo(inp, ("list", sort, pin, *inp.key), compute)

    def item_detail(self, item_id: int) -> dict:
        inp = self._inputs()
        return self._memo(
            inp, ("item", int(item_id), *inp.key), lambda: self._item(inp, int(item_id))
        )

    def _item(self, inp: ViewInputs, item_id: int) -> dict:
        item = next((i for i in inp.items if i.item_id == item_id), None)
        if item is None:
            return {"missing": True, "note": "This item is not in the archive."}
        lo, hi = inp.lo, inp.hi
        detail = self._details(inp).get(item_id, {})
        vendor = detail.get("vendor_price")
        hourly = series.hourly(inp.data_dir, [item_id])
        history = int(hourly["hour"].dt.tz_convert(vd.TZ).dt.date.nunique()) if len(hourly) else 0
        start, end = vd.utc_bounds(lo, hi)
        window = hourly[(hourly["hour"] >= start) & (hourly["hour"] < end)].reset_index(drop=True)
        ctx = Context(inp.data_dir, [item_id], lo, hi)
        frames = []
        for key in EVENT_JOBS:
            try:
                ev = run_pattern(key, ctx).events
            except Exception:  # noqa: BLE001 - markers are optional, the chart is not
                ev = None
            if ev is not None and len(ev):
                frames.append(ev[ev["item_id"] == item_id])
        events = (
            pd.concat(frames, ignore_index=True).sort_values("at") if frames else vd.empty_events()
        )
        latest = ctx.latest
        groups = [g.name for g in inp.groups if g.matches(item)]
        return {
            "head": vd.item_header(item, detail.get("subclass"), groups, history),
            "tiles": vd.item_tiles(
                item,
                latest.iloc[-1] if len(latest) else None,
                window,
                vd.week_change(self._week(inp)).get(item_id),  # as in the item list
                vendor,
                lo,
                hi,
            ),
            "chart": vd.price_chart(window, events, vendor, lo, hi),
            "profile": vd.hour_profile(window, lo, hi),
            "events": vd.item_events(events, {item_id: item.name}, lo, hi),
            "groups": [{"name": g.name, "member": g.name in groups} for g in inp.groups],
        }

    # Patterns ----------------------------------------------------------------------------
    # Spec: docs/superpowers/specs/2026-11-17-patterns-movers-views.md

    def _pattern_ctx(self, inp: ViewInputs) -> Context:
        """One Context per inputs: every job (and every row click) reads hourly once."""
        return self._memo(
            inp, ("pctx", *inp.key), lambda: Context(inp.data_dir, inp.ids, inp.lo, inp.hi)
        )

    def _pattern_run(self, inp: ViewInputs, key: str) -> PatternResult:
        ctx = self._pattern_ctx(inp)
        return self._memo(inp, ("prun", key, *inp.key), lambda: run_pattern(key, ctx))

    def _waiting(self, inp: ViewInputs) -> tuple[set[str], dict[str, str]]:
        """(waiting, empty): jobs whose input the collector has not filled yet at all
        (recipes, builds, vendor prices), and jobs whose input exists but not in the
        selected date range or filter (key -> note for the table).

        Emptiness is tested on the whole archive, not on the windowed Context.
        """

        def compute() -> tuple[set[str], dict[str, str]]:
            ctx = self._pattern_ctx(inp)
            waiting: set[str] = set()
            empty: dict[str, str] = {}
            if ctx.recipes.empty:  # recipes are never windowed or filtered
                waiting.add("processing_spreads")
            if series.builds(inp.data_dir).empty:
                waiting.add("build_effects")
            elif ctx.builds.empty:
                empty["build_effects"] = pv.NO_BUILDS_IN_RANGE

            def has_vendor(d: pd.DataFrame) -> bool:
                return bool((pd.to_numeric(d["vendor_price"], errors="coerce") > 0).any())

            if not has_vendor(series.item_details(inp.data_dir)):
                waiting.add("vendor_floor")
            elif not has_vendor(ctx.details):
                empty["vendor_floor"] = pv.NO_VENDOR_IN_FILTER
            return waiting, empty

        return self._memo(inp, ("waiting", *inp.key), compute)

    def patterns(
        self,
        key: str | None = None,
        select: str | int | None = None,
        item: int | None = None,
        sort: str | None = None,
    ) -> dict:
        """One pattern tab: tabs, basis line, state, charts for the selected row, ranked table."""
        inp = self._inputs()
        key = key if key in REGISTRY else pv.DEFAULT_KEY
        item = None if item is None else int(item)
        select = None if select is None else str(select)
        return self._memo(
            inp,
            ("patterns", key, select, item, sort, *inp.key),
            lambda: self._patterns(inp, key, select, item, sort),
        )

    def _patterns(
        self, inp: ViewInputs, key: str, select: str | None, item: int | None, sort: str | None
    ) -> dict:
        spec = REGISTRY[key]
        st = inp.status
        history = archive_days(st)
        ctx = self._pattern_ctx(inp)
        waiting, empty = self._waiting(inp)
        out: dict[str, Any] = {
            "sub": (
                f"{fmt.thousands(len(inp.shown))} of {plural(len(inp.items), 'item')}"
                f" · {plural(history, 'day')} of history"
            ),
            # "needs data" only when the archive is short: a short date range is the
            # user's choice and the tab explains it (window_gap).
            "tabs": pv.tabs(history, waiting),
            "key": key,
            "title": spec.title,
        }
        try:
            result = self._pattern_run(inp, key)
        except Exception as exc:  # noqa: BLE001 - one failing job must not break the view
            return {**out, "state": "error", "error": _failed(exc)}
        out["basis"] = pv.basis(result)
        if not result.ready:
            if not result.days_used:
                out["basis"]["lead"] = "No data yet"
            short_archive = history < spec.min_days
            if not result.days_used:
                out["basis"]["text"] = ""
            elif short_archive:
                out["basis"]["text"] = f" of data so far · needs {plural(spec.min_days, 'day')}"
            else:
                out["basis"]["text"] = (
                    f" in this date range · needs at least {plural(spec.min_days, 'day')}"
                )
            out["state"] = "history"
            out["gap"] = pattern_gap(
                spec.title,
                needed=spec.min_days,
                window_days=result.days_used,
                archive_days=history,
                last_day=st.last_day or inp.hi,
            )
            return out
        if key in waiting:
            title, text = pv.WAITING[key]
            out["basis"]["text"] = out["basis"]["text"].split(" · ")[0] + " · nothing to check yet"
            return {**out, "state": "waiting", "waiting": {"title": title, "text": text}}
        try:
            body = pv.build(result, ctx, select=select, item=item, sort=sort)
        except Exception as exc:  # noqa: BLE001
            return {**out, "state": "error", "error": _failed(exc)}
        if key in empty and not body["table"]["rows"]:
            body["table"]["note"] = empty[key]
        return {**out, "state": "ready", **body}

    # Movers & outliers --------------------------------------------------------------------

    def movers(self, rng: str = mv.DEFAULT_RANGE) -> dict:
        """Biggest risers and fallers over 24 h, 7 d or 30 d (the filtered items)."""
        inp = self._inputs()
        rng = rng if rng in mv.RANGES else mv.DEFAULT_RANGE

        def compute() -> dict:
            sub = f"{fmt.thousands(len(inp.shown))} of {plural(len(inp.items), 'item')}"
            last = inp.status.last_day
            if last is None or not inp.shown:
                return {"sub": sub, **mv.movers(pd.DataFrame(), [], rng)}
            first = last - timedelta(days=mv.read_days(rng))
            hourly = series.hourly(inp.data_dir, inp.ids, first, last)
            return {"sub": sub, **mv.movers(hourly, inp.shown, rng)}

        return self._memo(inp, ("movers", rng, *inp.key), compute)

    def mispricings_now(self, threshold: float = mv.DEFAULT_THRESHOLD) -> dict:
        """Current mispricings (job `mispricings` over the last two days of snapshots)."""
        inp = self._inputs()
        threshold = mv.threshold_of(threshold)

        def compute() -> dict:
            last = inp.status.last_day
            if last is None or not inp.shown:
                return mv.mispricings_now(None, pd.DataFrame(), [], {}, threshold)
            ctx = Context(inp.data_dir, inp.ids, last - timedelta(days=1), last)
            result = self._memo(
                inp, ("mnow", *inp.key), lambda: (run_pattern("mispricings", ctx), ctx)
            )
            res, ctx = result
            group_of: dict[int, str] = {}
            for item in inp.shown:
                for g in inp.groups:
                    if g.matches(item):
                        group_of[item.item_id] = g.name
                        break
            return mv.mispricings_now(res, ctx.hourly, inp.shown, group_of, threshold)

        return self._memo(inp, ("mispricings_now", threshold, *inp.key), compute)

    def add_to_group(self, name: str, item_id: int) -> dict:
        """Adds one item to a group (by id) and saves the groups."""
        for g in self.groups:
            if g.name == name:
                g.add(int(item_id))
                save_groups(self.groups)
                break
        return self.state()


def _ids_key(ids: list[int] | None) -> tuple | None:
    return None if ids is None else tuple(sorted(ids))


def _failed(exc: Exception) -> str:
    return f"Could not compute this: {type(exc).__name__}: {exc}"
