"""`Pull latest data` (git pull --ff-only) never raises and never touches a failed archive."""

import os
import shutil
import stat
import subprocess

from coppertrail.ui.pull import can_pull, run_pull


def git(*args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        },
    )


def clones(tmp_path):
    """A bare origin, a pusher clone and the data-folder clone."""
    origin = tmp_path / "origin.git"
    git("init", "--bare", "-q", "-b", "main", str(origin), cwd=tmp_path)
    pusher = tmp_path / "pusher"
    git("clone", "-q", str(origin), str(pusher), cwd=tmp_path)
    (pusher / "a.txt").write_text("1")
    git("add", "a.txt", cwd=pusher)
    git("commit", "-q", "-m", "first", cwd=pusher)
    git("push", "-q", "origin", "HEAD:main", cwd=pusher)
    data = tmp_path / "data"
    git("clone", "-q", str(origin), str(data), cwd=tmp_path)
    return origin, pusher, data


def test_not_a_clone(tmp_path):
    assert not can_pull(tmp_path)
    r = run_pull(tmp_path)
    assert not r.ok and r.message == "The data folder is not a git clone"


def test_git_missing(tmp_path):
    (tmp_path / ".git").mkdir()
    r = run_pull(tmp_path, git="no-such-git-binary")
    assert not r.ok and r.message == "Pull failed · git could not be started"


def test_pull_from_local_remote(tmp_path):
    _, pusher, data = clones(tmp_path)
    (pusher / "b.txt").write_text("2")
    git("add", "b.txt", cwd=pusher)
    git("commit", "-q", "-m", "second", cwd=pusher)
    git("push", "-q", "origin", "HEAD:main", cwd=pusher)
    assert can_pull(data)
    r = run_pull(data)
    assert r.ok and r.message == "Pulled latest data"
    assert (data / "b.txt").exists()


def test_failed_pull_keeps_archive(tmp_path):
    origin, _, data = clones(tmp_path)
    origin.rename(tmp_path / "gone.git")  # read-only git objects block rmtree on Windows
    r = run_pull(data)
    assert not r.ok and r.message == "Pull failed · the local archive is unchanged" and r.detail
    assert (data / "a.txt").read_text() == "1"


def out(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def push_window(pusher, files, *, first=False):
    """Push an orphan `window` commit holding exactly `files` (a force-push after the first)."""
    git("checkout", "-q", "--orphan", "w-new", cwd=pusher)
    git("rm", "-rq", "--cached", ".", cwd=pusher)
    for f in pusher.iterdir():
        if f.name != ".git":
            f.unlink()
    for name, text in files.items():
        (pusher / name).write_text(text)
    git("add", *files, cwd=pusher)
    git("commit", "-q", "-m", "window", cwd=pusher)
    git("push", "-q", "--force", "origin", "HEAD:window", cwd=pusher)
    sha = out("rev-parse", "HEAD", cwd=pusher)
    git("checkout", "-q", "-f", "main", cwd=pusher)
    git("branch", "-q", "-D", "w-new", cwd=pusher)
    return sha


def test_pull_creates_window_worktree(tmp_path):
    origin, pusher, data = clones(tmp_path)
    sha = push_window(pusher, {"w1.txt": "old"})
    r = run_pull(data)
    assert r.ok and r.message == "Pulled latest data", r.detail
    assert (data / "window" / "w1.txt").read_text() == "old"
    assert out("rev-parse", "HEAD", cwd=data / "window") == sha
    assert out("status", "--porcelain", cwd=data) == ""  # window/ never shows up in main


def test_pull_after_window_force_push(tmp_path):  # Review Focus 5
    origin, pusher, data = clones(tmp_path)
    old = push_window(pusher, {"w1.txt": "old"})
    assert run_pull(data).ok
    new = push_window(pusher, {"w2.txt": "new"})
    (pusher / "b.txt").write_text("2")
    git("add", "b.txt", cwd=pusher)
    git("commit", "-q", "-m", "second", cwd=pusher)
    git("push", "-q", "origin", "HEAD:main", cwd=pusher)
    r = run_pull(data)
    assert r.ok, r.detail
    window = data / "window"
    assert sorted(f.name for f in window.iterdir() if f.name != ".git") == ["w2.txt"]
    assert out("rev-parse", "HEAD", cwd=window) == new
    assert (data / "b.txt").exists()  # main still fast-forwarded
    gone = subprocess.run(["git", "cat-file", "-e", old], cwd=data, capture_output=True)
    assert gone.returncode != 0  # the rewritten history does not linger locally


def test_pull_recreates_deleted_window_folder(tmp_path):
    origin, pusher, data = clones(tmp_path)
    push_window(pusher, {"w1.txt": "old"})
    assert run_pull(data).ok
    shutil.rmtree(data / "window", onexc=_force)
    r = run_pull(data)
    assert r.ok, r.detail
    assert (data / "window" / "w1.txt").read_text() == "old"


def test_pull_without_window_branch_still_pulls_main(tmp_path):
    _, pusher, data = clones(tmp_path)
    (pusher / "b.txt").write_text("2")
    git("add", "b.txt", cwd=pusher)
    git("commit", "-q", "-m", "second", cwd=pusher)
    git("push", "-q", "origin", "HEAD:main", cwd=pusher)
    r = run_pull(data)
    assert r.ok and r.message == "Pulled latest data", r.detail
    assert (data / "b.txt").exists() and not (data / "window").exists()


def test_main_not_fast_forward_reports_failure(tmp_path):
    _, pusher, data = clones(tmp_path)
    push_window(pusher, {"w1.txt": "old"})
    (pusher / "a.txt").write_text("theirs")
    git("commit", "-qam", "theirs", cwd=pusher)
    git("push", "-q", "origin", "HEAD:main", cwd=pusher)
    (data / "a.txt").write_text("mine")
    git("commit", "-qam", "mine", cwd=data)
    r = run_pull(data)
    assert not r.ok and r.message == "Pull failed · the local archive is unchanged" and r.detail
    assert (data / "a.txt").read_text() == "mine"
    assert not (data / "window").exists()


def test_plain_window_folder_is_never_reset(tmp_path):
    """A `window/` that is not a worktree: resetting there would reset main instead."""
    _, pusher, data = clones(tmp_path)
    push_window(pusher, {"w1.txt": "old"})
    (data / "window").mkdir()
    (data / "window" / "keep.txt").write_text("x")
    head = out("rev-parse", "HEAD", cwd=data)
    r = run_pull(data)
    assert not r.ok and r.message == "Pull failed · the local archive is unchanged" and r.detail
    assert out("rev-parse", "HEAD", cwd=data) == head and (data / "a.txt").read_text() == "1"
    assert (data / "window" / "keep.txt").read_text() == "x"


def _force(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)  # git marks pack files read-only on Windows
    func(path)
