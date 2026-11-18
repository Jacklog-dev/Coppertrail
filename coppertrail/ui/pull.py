"""Pull latest data, the GUI's only network action.

The data folder is a clone of the data repo's `main` branch, pulled `--ff-only`. Its
`window` branch (copied data, rewritten daily) cannot be pulled, so it lives in a second
checkout, `<data>/window/`: a detached git worktree that is reset to `origin/window`,
after which the old window history is dropped from the local object store.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PULLED = "Pulled latest data"
COMMAND = "git pull --ff-only"
NOT_A_CLONE = "The data folder is not a git clone"
FAILED = "Pull failed · the local archive is unchanged"
NO_GIT = "Pull failed · git could not be started"

WINDOW = "window"  # branch name and checkout folder inside the data folder
NOT_A_WORKTREE = "window/ exists but is not a git worktree; move it away and pull again"


@dataclass(frozen=True)
class PullResult:
    ok: bool
    message: str
    detail: str = ""
    returncode: int | None = None  # git's exit code, None when git did not run to the end


class _GitFailed(Exception):
    def __init__(self, result: PullResult):
        self.result = result


def can_pull(data_dir: Path) -> bool:
    return (data_dir / ".git").exists()


def run_pull(data_dir: Path, git: str = "git", timeout: float = 300) -> PullResult:
    """Never raises. A failed fast-forward pull leaves the working tree as it was."""
    if not can_pull(data_dir):
        return PullResult(False, NOT_A_CLONE)
    log: list[str] = []

    def run(*args: str) -> str:
        try:
            proc = subprocess.run(
                [git, "-C", str(data_dir), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},  # never wait for a password
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except subprocess.TimeoutExpired:
            raise _GitFailed(PullResult(False, NO_GIT, "git timed out")) from None
        except OSError as exc:
            raise _GitFailed(PullResult(False, NO_GIT, str(exc))) from None
        log.extend(s for s in (proc.stdout.strip(), proc.stderr.strip()) if s)
        if proc.returncode != 0:
            raise _GitFailed(PullResult(False, FAILED, "\n".join(log), proc.returncode))
        return proc.stdout

    try:
        run("pull", "--ff-only")
        if run("ls-remote", "--heads", "origin", WINDOW).strip():
            _sync_window(data_dir, run, log)
    except _GitFailed as failed:
        return failed.result
    return PullResult(True, PULLED, "\n".join(log), 0)


def _sync_window(data_dir: Path, run, log: list[str]) -> None:
    window = data_dir / WINDOW
    run("fetch", "origin", f"+refs/heads/{WINDOW}:refs/remotes/origin/{WINDOW}")
    run("worktree", "prune")  # forget a window/ folder that was deleted by hand
    if window.exists() and not (window / ".git").is_file():
        # Without its own .git file, git in window/ would act on main: never reset there.
        log.append(NOT_A_WORKTREE)
        raise _GitFailed(PullResult(False, FAILED, "\n".join(log)))
    if window.exists():
        run("-C", WINDOW, "reset", "--hard", "--quiet", f"origin/{WINDOW}")
    else:
        run("worktree", "add", "--detach", "--quiet", WINDOW, f"origin/{WINDOW}")
        _exclude(data_dir, f"/{WINDOW}/")
    run("worktree", "prune")
    # The branch is rewritten daily: drop the old commits' reflog entries, then the objects.
    run("reflog", "expire", "--expire-unreachable=now", "--all")
    run("gc", "--prune=now", "--quiet")


def _exclude(data_dir: Path, pattern: str) -> None:
    """Keep window/ out of main's `git status` (local only, never committed)."""
    info = data_dir / ".git" / "info"
    exclude = info / "exclude"
    try:
        lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if pattern not in lines:
            info.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as f:
                f.write(("\n" if lines else "") + pattern + "\n")
    except OSError:
        pass  # cosmetic: main's status shows window/ as untracked, nothing breaks
