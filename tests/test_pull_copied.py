"""Pull latest data with copied data: the copied-data artifact replaces window/ only when
both the download and the git pull worked; old copies are pruned locally."""

import io
import subprocess
import zipfile
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from test_pull import clones, git

from coppertrail.collector.store import ITEMS, Store
from coppertrail.ui.bridge import pull_failure
from coppertrail.ui.pull import (
    DOWNLOAD_FAILED,
    FAILED,
    NO_GH,
    PULLED,
    PullResult,
    _Failed,
    gh_download,
    prune_copied,
    run_pull,
)

TODAY = date(2026, 11, 19)


def none(data_dir):
    return None  # no artifact available


def out(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


def serve(files):
    return lambda data_dir: zipped(files)


def push_main(pusher, name="b.txt"):
    (pusher / name).write_text("2")
    git("add", name, cwd=pusher)
    git("commit", "-q", "-m", name, cwd=pusher)
    git("push", "-q", "origin", "HEAD:main", cwd=pusher)


def listing(data):
    w = data / "window"
    return sorted(p.relative_to(w).as_posix() for p in w.rglob("*") if p.is_file())


def test_pull_unpacks_copied_data_into_window(tmp_path):
    _, pusher, data = clones(tmp_path)
    push_main(pusher)
    files = {
        "blizzard/items/2026-11-19.parquet": b"x",
        "blizzard/recipes/2026-11-18.parquet": b"y",
        "notes.txt": b"skipped",  # only parquet files
        "../escape.parquet": b"no",  # never outside window/
    }
    r = run_pull(data, download=serve(files), today=TODAY)
    assert r.ok and r.message == PULLED, r.detail
    assert listing(data) == [
        "blizzard/items/2026-11-19.parquet",
        "blizzard/recipes/2026-11-18.parquet",
    ]
    assert not (tmp_path / "escape.parquet").exists() and not (data / "escape.parquet").exists()
    assert (data / "b.txt").exists()
    assert out("status", "--porcelain", cwd=data) == ""  # window/ never shows up in main


def test_new_artifact_replaces_window(tmp_path):
    _, _, data = clones(tmp_path)
    assert run_pull(data, download=serve({"blizzard/items/a.parquet": b"1"})).ok
    assert run_pull(data, download=serve({"blizzard/items/b.parquet": b"2"})).ok
    assert listing(data) == ["blizzard/items/b.parquet"]


def test_no_artifact_keeps_window(tmp_path):
    _, _, data = clones(tmp_path)
    assert run_pull(data, download=serve({"blizzard/items/a.parquet": b"1"})).ok
    r = run_pull(data, download=none)
    assert r.ok and "no artifact" in r.detail
    assert listing(data) == ["blizzard/items/a.parquet"]


def test_download_failure_changes_nothing(tmp_path):
    _, pusher, data = clones(tmp_path)
    assert run_pull(data, download=serve({"blizzard/items/a.parquet": b"1"})).ok
    push_main(pusher)

    def broken(data_dir):
        raise _Failed(PullResult(False, DOWNLOAD_FAILED, "HTTP 404", 1))

    r = run_pull(data, download=broken)
    assert not r.ok and r.message == DOWNLOAD_FAILED
    assert not (data / "b.txt").exists()  # main not pulled either
    assert listing(data) == ["blizzard/items/a.parquet"]
    assert not (data / ".window-new").exists()


def test_main_not_fast_forward_keeps_window(tmp_path):
    _, pusher, data = clones(tmp_path)
    assert run_pull(data, download=serve({"blizzard/items/a.parquet": b"1"})).ok
    (pusher / "a.txt").write_text("theirs")
    git("commit", "-qam", "theirs", cwd=pusher)
    git("push", "-q", "origin", "HEAD:main", cwd=pusher)
    (data / "a.txt").write_text("mine")
    git("commit", "-qam", "mine", cwd=data)
    r = run_pull(data, download=serve({"blizzard/items/b.parquet": b"2"}))
    assert not r.ok and r.message == FAILED and r.detail
    assert (data / "a.txt").read_text() == "mine"
    assert listing(data) == ["blizzard/items/a.parquet"]  # the new download was discarded
    assert not (data / ".window-new").exists()


def test_old_window_worktree_is_migrated(tmp_path):
    """The old layout: window/ as a worktree of a force-pushed `window` branch."""
    _, pusher, data = clones(tmp_path)
    git("checkout", "-q", "--orphan", "w", cwd=pusher)
    git("rm", "-rq", "--cached", ".", cwd=pusher)
    (pusher / "a.txt").unlink()
    (pusher / "old.txt").write_text("old")
    git("add", "-A", cwd=pusher)
    git("commit", "-q", "-m", "window", cwd=pusher)
    git("push", "-q", "origin", "HEAD:window", cwd=pusher)
    old = out("rev-parse", "HEAD", cwd=pusher)
    git("checkout", "-q", "-f", "main", cwd=pusher)
    git("fetch", "-q", "origin", "+refs/heads/window:refs/remotes/origin/window", cwd=data)
    git("worktree", "add", "--detach", "-q", "window", "origin/window", cwd=data)
    assert (data / "window" / "old.txt").exists()

    r = run_pull(data, download=serve({"blizzard/items/a.parquet": b"1"}))
    assert r.ok, r.detail
    assert listing(data) == ["blizzard/items/a.parquet"]
    assert out("worktree", "list", "--porcelain", cwd=data).count("worktree ") == 1
    assert out("for-each-ref", "refs/remotes/origin/window", cwd=data) == ""
    gone = subprocess.run(["git", "cat-file", "-e", old], cwd=data, capture_output=True)
    assert gone.returncode != 0  # the old copied data is gone from the local clone


def test_prune_copied_drops_old_rows(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    now = datetime(2026, 11, 19, 12, tzinfo=UTC)
    rows = [
        {"item_id": 1, "found": True, "fetched_at": now - timedelta(days=31)},
        {"item_id": 2, "found": True, "fetched_at": now - timedelta(days=2)},
    ]
    s.write_day(ITEMS, (now - timedelta(days=2)).date(), pd.DataFrame(rows))
    assert prune_copied(tmp_path, TODAY) >= 1
    kept = pd.read_parquet(s.path(ITEMS, TODAY))
    assert kept["item_id"].tolist() == [2]


def test_prune_copied_without_window_is_noop(tmp_path):
    assert prune_copied(tmp_path, TODAY) == 0


def test_gh_missing(tmp_path):
    with pytest.raises(_Failed) as exc:
        gh_download(tmp_path, gh="no-such-gh-binary")
    assert exc.value.result.message == NO_GH


def test_gh_failures_explain_themselves():
    at = datetime(2026, 11, 19, 12, tzinfo=UTC)
    no_gh = pull_failure(PullResult(False, NO_GH, "not found"), as_of=None, at=at)
    assert "gh auth login" in no_gh["cause"] and no_gh["request"].startswith("gh api")
    detail = "warning\nHTTP 404: Not Found"
    dl = pull_failure(PullResult(False, DOWNLOAD_FAILED, detail, 1), as_of=None, at=at)
    assert dl["cause"] == "The item data could not be downloaded: HTTP 404: Not Found."
