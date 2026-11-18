import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from coppertrail.collector.store import HOURLY, HOUSE, ITEMS, RECIPES, Store
from coppertrail.collector.window import prune_summaries, prune_window, rebuild_branch

TODAY = date(2026, 11, 19)
NOW = datetime(2026, 11, 19, 0, 50, tzinfo=UTC)

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(repo, *args):
    out = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def store(tmp_path):
    return Store(tmp_path, tmp_path / "window")


def items_row(item_id, at, quality="COMMON"):
    return {"item_id": item_id, "found": True, "quality": quality, "fetched_at": at}


def test_prune_window_keeps_newest_items_within_days(tmp_path):
    s = store(tmp_path)
    d40, d10, d1 = (NOW - timedelta(days=n) for n in (40, 10, 1))
    s.write_day(ITEMS, d40.date(), pd.DataFrame([items_row(1, d40), items_row(2, d40)]))
    s.write_day(ITEMS, d10.date(), pd.DataFrame([items_row(2, d10, "RARE"), items_row(3, d10)]))
    s.write_day(ITEMS, d1.date(), pd.DataFrame([items_row(3, d1, "EPIC")]))
    s.write_day(RECIPES, d40.date(), pd.DataFrame([{"recipe_id": 1, "fetched_at": d40}]))
    s.write_day(RECIPES, d10.date(), pd.DataFrame([{"recipe_id": 2, "fetched_at": d10}]))
    s.write_day(RECIPES, d1.date(), pd.DataFrame([{"recipe_id": 3, "fetched_at": d1}]))

    deleted = prune_window(s, TODAY, 30)

    assert s.files(ITEMS) == [s.path(ITEMS, TODAY)]
    kept = pd.read_parquet(s.path(ITEMS, TODAY)).set_index("item_id")
    assert sorted(kept.index) == [2, 3]  # item 1 is 40 days old
    assert kept.loc[2, "quality"] == "RARE" and kept.loc[3, "quality"] == "EPIC"
    assert s.files(RECIPES) == [s.path(RECIPES, d1.date())]
    assert set(deleted) == {
        s.path(ITEMS, d40.date()),
        s.path(ITEMS, d10.date()),
        s.path(ITEMS, d1.date()),
        s.path(RECIPES, d40.date()),
        s.path(RECIPES, d10.date()),
    }


def test_prune_window_drops_too_old_recipes_and_all_items(tmp_path):
    s = store(tmp_path)
    old = NOW - timedelta(days=30)
    s.write_day(ITEMS, old.date(), pd.DataFrame([items_row(1, old)]))
    s.write_day(RECIPES, old.date(), pd.DataFrame([{"recipe_id": 1, "fetched_at": old}]))
    prune_window(s, TODAY, 30)
    assert s.files(ITEMS) == [] and s.files(RECIPES) == []


def test_prune_window_empty_is_noop(tmp_path):
    assert prune_window(store(tmp_path), TODAY, 30) == []


@needs_git
def test_rebuild_branch_leaves_single_commit(tmp_path):
    repo = tmp_path / "window"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "window")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / "items").mkdir()
    old = repo / "items" / "2026-10-01.parquet"
    old.write_bytes(b"old copied data")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "day 1")
    old_blob = git(repo, "rev-parse", "HEAD:items/2026-10-01.parquet")
    (repo / "items" / "2026-11-19.parquet").write_bytes(b"new copied data")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "day 2")
    old.unlink()

    sha = rebuild_branch(repo, "window 2026-11-19")

    assert git(repo, "rev-list", "--count", "HEAD") == "1"
    assert git(repo, "rev-parse", "HEAD") == sha
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "window"
    assert git(repo, "log", "-1", "--format=%s") == "window 2026-11-19"
    assert git(repo, "ls-files") == "items/2026-11-19.parquet"
    assert old_blob not in git(repo, "rev-list", "--objects", "--all")
    assert git(repo, "branch", "--list") == "* window"


def _hour_files(s, table, day):
    at = datetime(day.year, day.month, day.day, 12, 22, tzinfo=UTC)
    if table is HOURLY:
        df = pd.DataFrame(
            [
                {
                    "item_id": 1,
                    "hour": at.replace(minute=0),
                    "observed_at": at,
                    "quantity": 1,
                    "auctions": 1,
                    "source": "blizzard",
                }
            ]
        )
    else:
        df = pd.DataFrame([{"hour": at.replace(minute=0), "observed_at": at, "source": "blizzard"}])
    return s.write_hour(table, at, df)


def test_prune_summaries_zero_keeps_all(tmp_path):
    s = store(tmp_path)
    _hour_files(s, HOURLY, date(2025, 1, 1))
    assert prune_summaries(s, TODAY, 0) == []
    assert len(s.files(HOURLY)) == 1


def test_prune_summaries_30_deletes_older_hour_dirs(tmp_path):
    s = store(tmp_path)
    old, edge, recent = (
        TODAY - timedelta(days=40),
        TODAY - timedelta(days=30),
        TODAY - timedelta(days=29),
    )
    for table in (HOURLY, HOUSE):
        for day in (old, edge, recent):
            _hour_files(s, table, day)
    deleted = prune_summaries(s, TODAY, 30)
    for table in (HOURLY, HOUSE):
        assert [p.parent.name for p in s.files(table)] == [recent.isoformat()]
        assert not (s.root(table) / old.isoformat()).exists()
    assert set(deleted) == {s.root(t) / d.isoformat() for t in (HOURLY, HOUSE) for d in (old, edge)}


@needs_git
def test_rebuild_branch_twice_and_unborn(tmp_path):
    repo = tmp_path / "window"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "window")  # no commit yet
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / "a.parquet").write_bytes(b"x")
    rebuild_branch(repo, "window 2026-11-19")
    (repo / "b.parquet").write_bytes(b"y")
    rebuild_branch(repo, "window 2026-11-20")
    assert git(repo, "rev-list", "--count", "HEAD") == "1"
    assert git(repo, "log", "-1", "--format=%s") == "window 2026-11-20"
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "ls-files").split() == ["a.parquet", "b.parquet"]


@needs_git
def test_rebuild_branch_refuses_other_branch(tmp_path):
    repo = tmp_path / "data"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / "a").write_text("a")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "one")
    (repo / "b").write_text("b")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "two")
    with pytest.raises(RuntimeError, match="main"):
        rebuild_branch(repo, "window 2026-11-19")
    assert git(repo, "rev-list", "--count", "HEAD") == "2"
