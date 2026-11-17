"""One collector run: price table -> watchlist -> hourly/scans/economy -> merge -> reports.

Resumable: each fetched unit is staged as its own file (see store.py). If a run dies,
the next invocation resumes it (when recent) or merges what it got and starts fresh.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import parse
from .api import AhledgerClient, ApiError
from .config import Config, check_cutoff
from .gaps import format_summary, gap_report
from .store import (
    BUILDS,
    ECONOMY,
    GAPS,
    HOURLY,
    ITEMS,
    POPULATION,
    RECIPES,
    RUNS,
    SCANS,
    SNAPSHOT,
    WATCHLIST,
    Store,
)
from .watchlist import Entry, build_watchlist, rule_candidates

log = logging.getLogger("coppertrail.collector")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_LOCKED = 2
EXIT_CUTOFF = 3

LOCK_STALE_S = 20 * 60  # a lock not refreshed for this long belongs to a dead run
MERGE_TABLES = (
    SNAPSHOT,
    ITEMS,
    WATCHLIST,
    ECONOMY,
    POPULATION,
    RECIPES,
    BUILDS,
    HOURLY,
    SCANS,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class LockError(Exception):
    pass


class RunLock:
    """Portable single-instance lock: exclusive create, refreshed as a heartbeat."""

    def __init__(self, path: Path):
        self.path = path

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age < LOCK_STALE_S:
                raise LockError(
                    f"another collector run holds {self.path} (heartbeat {age:.0f}s ago)"
                )
            log.warning("removing stale lock %s (%.0f min old)", self.path, age / 60)
            self.path.unlink(missing_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(f"pid={os.getpid()} started={utcnow().isoformat()}\n")

    def heartbeat(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.utime(self.path)

    def release(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclass
class RunState:
    run_id: str
    started_at: str
    requests: int = 0
    errors: int = 0
    retries: int = 0
    pricetable_scanned_at: str | None = None
    notes: list[str] = field(default_factory=list)

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> RunState:
        return cls(**json.loads(path.read_text()))


class Collector:
    def __init__(
        self,
        cfg: Config,
        data_dir: Path,
        client: AhledgerClient | None = None,
        now: Callable[[], datetime] = utcnow,
    ):
        self.cfg = cfg
        self.store = Store(data_dir)
        self.client = client or AhledgerClient(cfg)
        self.now = now
        self.lock = RunLock(self.store.data_dir / ".collector.lock")
        self.state: RunState | None = None
        self._base_stats = (0, 0, 0)

    # Helpers ------------------------------------------------------------------

    def _state_path(self, run_id: str) -> Path:
        return self.store.run_dir(run_id) / "state.json"

    def _sync_stats(self) -> None:
        s = self.client.stats
        b = self._base_stats
        self.state.requests = b[0] + s.requests
        self.state.errors = b[1] + s.errors
        self.state.retries = b[2] + s.retries
        self.state.save(self._state_path(self.state.run_id))
        self.lock.heartbeat()

    def _note(self, msg: str) -> None:
        log.warning(msg)
        self.state.notes.append(msg)

    # Entry point --------------------------------------------------------------

    def run(self) -> int:
        today = self.now().date()
        cutoff = check_cutoff(self.cfg, today)
        if not cutoff.allowed:
            log.error(cutoff.message)
            return EXIT_CUTOFF
        if cutoff.message:
            log.warning(cutoff.message)
        try:
            self.lock.acquire()
        except LockError as exc:
            log.error("%s", exc)
            return EXIT_LOCKED
        try:
            run_id = self._recover_leftovers()
            return self._run(run_id, cutoff.message)
        finally:
            self.lock.release()

    def _recover_leftovers(self) -> str | None:
        """Finalize old interrupted runs; return the id of one recent enough to resume."""
        resume = None
        for rid in sorted(self.store.staged_runs(), reverse=True):
            sp = self._state_path(rid)
            if not sp.exists():
                log.warning("staging dir %s has no state, removing", rid)
                self.store.drop_run(rid)
                continue
            st = RunState.load(sp)
            age = self.now() - datetime.fromisoformat(st.started_at)
            if resume is None and age < timedelta(hours=self.cfg.resume_max_age_hours):
                log.info("resuming interrupted run %s (started %s ago)", rid, age)
                resume = rid
            else:
                log.info("finalizing interrupted run %s", rid)
                self.state = st
                self._finish(st, status="interrupted", watch=None, planned=(0, 0))
                self.state = None
        return resume

    def _run(self, resume_id: str | None, cutoff_msg: str) -> int:
        if resume_id:
            self.state = RunState.load(self._state_path(resume_id))
            self._base_stats = (self.state.requests, self.state.errors, self.state.retries)
            self.state.notes.append(f"resumed at {self.now().isoformat()}")
        else:
            start = self.now()
            run_id = start.strftime("%Y%m%dT%H%M%SZ")
            self.state = RunState(run_id=run_id, started_at=start.isoformat())
            self.store.run_dir(run_id).mkdir(parents=True, exist_ok=True)
        if cutoff_msg:
            self.state.notes.append(cutoff_msg)
        st = self.state
        self._sync_stats()
        started = datetime.fromisoformat(st.started_at)
        log.info("run %s, market %s, data dir %s", st.run_id, self.cfg.market, self.store.data_dir)

        try:
            watch = self._watchlist(st, started)
        except ApiError as exc:
            self._note(f"fatal: could not build the watchlist: {exc}")
            self._sync_stats()
            self._finish(st, status="failed", watch=None, planned=(0, 0))
            return EXIT_FAILED

        self._economy(st)
        self._population(st)
        self._recipes(st)
        self._builds(st)
        hourly_failed = self._series(st, watch, HOURLY, "7d", "hour", started)
        scan_entries = [e for e in watch if e.scans]
        self._series(st, scan_entries, SCANS, "24h", "observed_at", started, budget=True)
        self._item_details(st, watch, started)

        errors_ratio = hourly_failed / max(1, len(watch))
        status = "ok" if hourly_failed == 0 else ("partial" if errors_ratio < 0.05 else "failed")
        self._finish(st, status=status, watch=watch, planned=(len(watch), len(scan_entries)))
        return EXIT_OK if status != "failed" else EXIT_FAILED

    # Steps --------------------------------------------------------------------

    def _watchlist(self, st: RunState, started: datetime) -> list[Entry]:
        if self.store.is_staged(st.run_id, WATCHLIST, "watchlist"):
            tbl = self.store.read_staged(st.run_id, WATCHLIST)
            entries = [
                Entry(r["item_id"], r["reason"], r["turnover"], r["scans"])
                for r in tbl.sort_by("rank").to_pylist()
            ]
            log.info("watchlist from staging: %d items", len(entries))
            return entries

        pt = parse.parse_pricetable(self.client.pricetable())
        self._sync_stats()
        if pt.market != self.cfg.market:
            raise ApiError(f"price table is for {pt.market}, expected {self.cfg.market}")
        st.pricetable_scanned_at = pt.scanned_at.isoformat()
        log.info("price table: %d items, scanned %s", len(pt.rows), pt.scanned_at)
        self.store.stage(st.run_id, SNAPSHOT, "pricetable", parse.snapshot_rows(pt, st.run_id))

        sticky = self._sticky_ids(started)
        qualities = self._known_qualities(st)
        detailed = self._detailed_ids()  # a /v1/items row is newer and fuller than tooltip
        need = [
            i
            for i in dict.fromkeys(rule_candidates(pt.rows, self.cfg) + sorted(sticky))
            if i not in qualities and i not in detailed
        ]
        if need:
            log.info("fetching master data for %d items via /tooltip", len(need))
        for n, i in enumerate(range(0, len(need), 100)):
            chunk = need[i : i + 100]
            try:
                rows = parse.item_rows(self.client.tooltip(chunk), self.now())
            except ApiError as exc:
                self._note(
                    f"tooltip chunk {n} failed, quality unknown for {len(chunk)} items: {exc}"
                )
                continue
            finally:
                self._sync_stats()
            self.store.stage(st.run_id, ITEMS, f"tooltip-{n:03d}", rows)
            qualities.update({r["item_id"]: r["quality"] for r in rows})

        entries = build_watchlist(pt.rows, self.cfg, qualities, sticky)
        reasons: dict[str, int] = {}
        for e in entries:
            reasons[e.reason] = reasons.get(e.reason, 0) + 1
        log.info(
            "watchlist: %d items %s, %d with per-scan data",
            len(entries),
            reasons,
            sum(e.scans for e in entries),
        )
        self.store.stage(
            st.run_id,
            WATCHLIST,
            "watchlist",
            [
                {
                    "run_id": st.run_id,
                    "run_started_at": started,
                    "item_id": e.item_id,
                    "rank": k,
                    "reason": e.reason,
                    "turnover": e.turnover,
                    "scans": e.scans,
                }
                for k, e in enumerate(entries)
            ],
        )
        return entries

    def _sticky_ids(self, started: datetime) -> set[int]:
        since = started - timedelta(days=self.cfg.sticky_days)
        tbl = self.store.query(
            "SELECT DISTINCT item_id FROM {w} WHERE reason IN ('bulk', 'valuable') "
            "AND run_started_at >= ? AND run_started_at < ?",
            [since, started],
            w=WATCHLIST.name,
        )
        return set(tbl.column("item_id").to_pylist()) if tbl is not None else set()

    def _known_qualities(self, st: RunState) -> dict[int, str]:
        out: dict[int, str] = {}
        for tbl in (self.store.read_all(ITEMS), self.store.read_staged(st.run_id, ITEMS)):
            if tbl is None:
                continue
            for r in tbl.sort_by("fetched_at").select(["item_id", "quality"]).to_pylist():
                if r["quality"]:
                    out[r["item_id"]] = r["quality"]
        return out

    def _economy(self, st: RunState) -> None:
        if self.store.is_staged(st.run_id, ECONOMY, "economy"):
            return
        try:
            rows = parse.economy_rows(self.client.economy(), self.now(), st.run_id)
            self.store.stage(st.run_id, ECONOMY, "economy", rows)
            log.info("economy: %d rows", len(rows))
        except (ApiError, KeyError, ValueError) as exc:
            self._note(f"economy failed: {exc}")
        self._sync_stats()

    def _population(self, st: RunState) -> None:
        if self.store.is_staged(st.run_id, POPULATION, "population"):
            return
        try:
            rows = parse.population_rows(self.client.population_csv(), self.now(), st.run_id)
            if rows:
                self.store.stage(st.run_id, POPULATION, "population", rows)
            log.info("population: %d rows", len(rows))
        except ApiError as exc:
            # Soft error: ahledger.com (not the API) sits behind a bot check.
            self._note(f"population CSV skipped: {exc}")
        self._sync_stats()

    def _recipes(self, st: RunState) -> None:
        if not self.cfg.fetch_recipes or self.store.is_staged(st.run_id, RECIPES, "recipes"):
            return
        try:
            rows = parse.recipe_rows(self.client.crafting(), self.now(), st.run_id)
            self.store.stage(st.run_id, RECIPES, "recipes", rows)
            log.info("recipes: %d rows", len(rows))
        except (ApiError, KeyError, ValueError) as exc:
            self._note(f"recipes failed: {exc}")
        self._sync_stats()

    def _builds(self, st: RunState) -> None:
        if not self.cfg.fetch_builds or self.store.is_staged(st.run_id, BUILDS, "builds"):
            return
        try:
            rows = parse.build_rows(self.client.builds_feed(), self.now(), st.run_id)
            self.store.stage(st.run_id, BUILDS, "builds", rows)
            log.info("builds: %d rows", len(rows))
        except (ApiError, ValueError, ET.ParseError) as exc:
            self._note(f"builds feed skipped: {exc}")
        self._sync_stats()

    def _detailed_ids(self) -> set[int]:
        """Items whose newest stored row came from /v1/items (any detail field set)."""
        tbl = self.store.read_all(ITEMS)
        if tbl is None or "vendor_price" not in tbl.column_names:
            return set()
        latest: dict[int, dict] = {}
        cols = ["item_id", "subclass", "required_level", "vendor_price"]
        for r in tbl.sort_by("fetched_at").select(cols).to_pylist():
            latest[r["item_id"]] = r
        return {
            i
            for i, r in latest.items()
            if r["subclass"] is not None
            or r["vendor_price"] is not None
            or r["required_level"] is not None
        }

    def _item_details(self, st: RunState, watch: list[Entry], started: datetime) -> None:
        """Subclass and vendor price for watchlist items without them, capped per run."""
        if not self.cfg.fetch_item_details:
            return
        known = self._detailed_ids()
        done = {n for n in self.store.staged_names(st.run_id, ITEMS) if n.startswith("item-")}
        todo = [
            e.item_id for e in watch if e.item_id not in known and f"item-{e.item_id}" not in done
        ][: max(0, self.cfg.item_details_per_run - len(done))]
        log.info("item details: %d to fetch", len(todo))
        deadline = started + timedelta(minutes=self.cfg.max_run_minutes)
        failed: list[int] = []
        for k, iid in enumerate(todo):
            if self.now() > deadline:
                self._note(f"item details: time budget reached, skipped {len(todo) - k} items")
                break
            try:
                row = parse.item_detail_row(self.client.item(iid), self.now())
                self.store.stage(st.run_id, ITEMS, f"item-{iid}", [row])
            except (ApiError, KeyError, ValueError) as exc:
                failed.append(iid)
                log.warning("item details %s failed: %s", iid, exc)
            self._sync_stats()
        if failed:
            self._note(f"item details failed for {len(failed)} items: {failed[:20]}")

    def _series(
        self,
        st: RunState,
        entries: list[Entry],
        table,
        range_: str,
        time_col: str,
        started: datetime,
        budget: bool = False,
    ) -> int:
        """Fetch one series per entry and stage it. Returns the number of failures."""
        done = self.store.staged_names(st.run_id, table)
        todo = [e for e in entries if str(e.item_id) not in done]
        log.info(
            "%s: %d items, %d already staged, %d to fetch",
            table.name,
            len(entries),
            len(entries) - len(todo),
            len(todo),
        )
        deadline = started + timedelta(minutes=self.cfg.max_run_minutes)
        failed = 0
        t0 = time.monotonic()
        for k, e in enumerate(todo, 1):
            if budget and self.now() > deadline:
                self._note(
                    f"{table.name}: time budget of {self.cfg.max_run_minutes:.0f} min reached, "
                    f"skipped {len(todo) - k + 1} items"
                )
                break
            try:
                payload = self.client.prices(e.item_id, range_)
                rows = parse.series_rows(payload, e.item_id, time_col, self.now(), st.run_id)
                self.store.stage(st.run_id, table, str(e.item_id), rows)
            except (ApiError, KeyError, ValueError) as exc:
                failed += 1
                log.warning("%s %s failed: %s", table.name, e.item_id, exc)
            self._sync_stats()
            if k % 50 == 0 or k == len(todo):
                rate = k / max(1e-9, time.monotonic() - t0) * 60
                eta = (len(todo) - k) / max(rate, 1e-9)
                log.info(
                    "%s: %d/%d (%.1f req/min, ~%.0f min left, %d failed)",
                    table.name,
                    k,
                    len(todo),
                    rate,
                    eta,
                    failed,
                )
        return failed

    # Finish -------------------------------------------------------------------

    def _finish(
        self, st: RunState, status: str, watch: list[Entry] | None, planned: tuple[int, int]
    ) -> None:
        """Merge staged files into day files, write gap report and run log, drop staging."""
        rid = st.run_id
        staged = {t.name: self.store.read_staged(rid, t) for t in MERGE_TABLES}
        for t in MERGE_TABLES:
            files = self.store.upsert(t, staged[t.name])
            if files:
                log.info("merged %s into %d day file(s)", t.name, len(files))

        hourly, scans = staged["hourly"], staged["scans"]
        oldest = newest = None
        if hourly is not None and hourly.num_rows:
            hours = hourly.column("hour").to_pylist()
            oldest, newest = min(hours), max(hours)

        finished = self.now()
        if watch is None:
            wl = staged["watchlist"]
            ids = wl.column("item_id").to_pylist() if wl is not None else []
        else:
            ids = [e.item_id for e in watch]
        if ids:
            rows, market_gaps = gap_report(
                self.store, ids, finished, self.cfg.gap_window_hours, rid
            )
            self.store.upsert(GAPS, self._arrow(GAPS, rows))
            log.info("%s", format_summary(rows, market_gaps))

        run_row = {
            "run_id": rid,
            "started_at": datetime.fromisoformat(st.started_at),
            "finished_at": finished,
            "status": status,
            "requests": st.requests,
            "errors": st.errors,
            "retries": st.retries,
            "items_planned": planned[0] or len(ids),
            "hourly_done": len(self.store.staged_names(rid, HOURLY)),
            "scans_planned": planned[1],
            "scans_done": len(self.store.staged_names(rid, SCANS)),
            "hourly_rows": hourly.num_rows if hourly is not None else 0,
            "scan_rows": scans.num_rows if scans is not None else 0,
            "oldest_seen": oldest,
            "newest_seen": newest,
            "pricetable_scanned_at": (
                datetime.fromisoformat(st.pricetable_scanned_at)
                if st.pricetable_scanned_at
                else None
            ),
            "api_archive_until": self.cfg.api_archive_until,
            "notes": "\n".join(st.notes),
            "fetched_at": finished,
        }
        self.store.upsert(RUNS, self._arrow(RUNS, [run_row]))
        log.info(
            "run %s %s: %d requests, %d errors, %d retries, hourly %d/%d items (%d rows), "
            "scans %d/%d items (%d rows), seen %s to %s",
            rid,
            status,
            st.requests,
            st.errors,
            st.retries,
            run_row["hourly_done"],
            run_row["items_planned"],
            run_row["hourly_rows"],
            run_row["scans_done"],
            planned[1],
            run_row["scan_rows"],
            oldest,
            newest,
        )
        self.store.drop_run(rid)

    @staticmethod
    def _arrow(table, rows):
        from .store import to_arrow

        return to_arrow(table, rows)
