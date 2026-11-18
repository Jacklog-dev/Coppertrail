"""`Pull latest data` (git pull --ff-only) never raises and never touches a failed archive."""

import os
import subprocess

from coppertrail.ui.pull import FAILED, PULLED, can_pull, run_pull


def none(data_dir):
    return None  # no copied-data artifact (test_pull_copied.py covers the download)


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
    r = run_pull(tmp_path, git="no-such-git-binary", download=none)
    assert not r.ok and r.message == "Pull failed · git could not be started"


def test_pull_from_local_remote(tmp_path):
    _, pusher, data = clones(tmp_path)
    (pusher / "b.txt").write_text("2")
    git("add", "b.txt", cwd=pusher)
    git("commit", "-q", "-m", "second", cwd=pusher)
    git("push", "-q", "origin", "HEAD:main", cwd=pusher)
    assert can_pull(data)
    r = run_pull(data, download=none)
    assert r.ok and r.message == PULLED
    assert (data / "b.txt").exists() and not (data / "window").exists()


def test_failed_pull_keeps_archive(tmp_path):
    origin, _, data = clones(tmp_path)
    origin.rename(tmp_path / "gone.git")  # read-only git objects block rmtree on Windows
    r = run_pull(data, download=none)
    assert not r.ok and r.message == FAILED and r.detail
    assert (data / "a.txt").read_text() == "1"
