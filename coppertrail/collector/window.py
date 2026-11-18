"""The 30-day window: prune copied Blizzard data and rebuild the window branch.

Blizzard's terms allow keeping copied API data for at most 30 days. The window branch
holds only that data and is rebuilt every night as a single orphan commit, so older
copies leave the branch's history when the workflow force-pushes it.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import date
from pathlib import Path

from .store import HOURLY, HOUSE, ITEMS, RECIPES, Store

log = logging.getLogger(__name__)

BRANCH = "window"


def _young(day: date, today: date, days: int) -> bool:
    """True while `day` is less than `days` days before `today`."""
    return (today - day).days < days


def prune_window(store: Store, today: date, copied_days: int) -> list[Path]:
    """Collapse ITEMS into `blizzard/items/<today>.parquet` (newest row per item, rows fetched
    `copied_days` or more days ago dropped) and keep only the newest RECIPES file while
    it is younger than `copied_days`. Returns the deleted files."""
    deleted: list[Path] = []
    item_files = store.files(ITEMS)
    if item_files:
        df = store.read(ITEMS).to_pandas()
        df = df.sort_values(["item_id", "fetched_at"], kind="stable")
        df = df.drop_duplicates("item_id", keep="last")
        df = df[[_young(t.date(), today, copied_days) for t in df["fetched_at"]]]
        target = store.path(ITEMS, today)
        if len(df):
            store.write_day(ITEMS, today, df)
        for f in item_files:
            if f != target or not len(df):
                f.unlink()
                deleted.append(f)

    recipe_files = store.files(RECIPES)
    keep = recipe_files[-1:] if recipe_files else []
    if keep and not _young(date.fromisoformat(keep[0].stem), today, copied_days):
        keep = []
    for f in recipe_files:
        if f not in keep:
            f.unlink()
            deleted.append(f)
    log.info("window: %d file(s) pruned", len(deleted))
    return deleted


def prune_summaries(store: Store, today: date, summary_retention_days: int) -> list[Path]:
    """Delete HOURLY and HOUSE day folders `summary_retention_days` or more days old.
    0 keeps them for good. Returns the deleted folders."""
    if summary_retention_days <= 0:
        return []
    deleted: list[Path] = []
    for table in (HOURLY, HOUSE):
        root = store.root(table)
        if not root.exists():
            continue
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                day = date.fromisoformat(d.name)
            except ValueError:
                continue
            if not _young(day, today, summary_retention_days):
                shutil.rmtree(d)
                deleted.append(d)
    log.info("summaries: %d day folder(s) deleted", len(deleted))
    return deleted


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def rebuild_branch(window_dir: Path, message: str) -> str:
    """Replace the checked-out window branch with one orphan commit of the current tree.
    Returns the new commit's sha. Pushing is left to the workflow.

    The commit is made with `commit-tree` (no parent) and `window` is pointed at it, so
    there is no temporary branch for an interrupted run to leave behind."""
    window_dir = Path(window_dir)
    current = _git(window_dir, "symbolic-ref", "--short", "HEAD")
    if current != BRANCH:
        raise RuntimeError(f"{window_dir} is on branch {current!r}, not {BRANCH!r}")
    _git(window_dir, "add", "-A")
    tree = _git(window_dir, "write-tree")
    sha = _git(window_dir, "commit-tree", tree, "-m", message)
    _git(window_dir, "update-ref", f"refs/heads/{BRANCH}", sha)
    log.info("window branch rebuilt as one commit")
    return sha
