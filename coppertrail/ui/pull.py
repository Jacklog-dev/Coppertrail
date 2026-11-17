"""Pull latest data: `git pull --ff-only` in the data folder, the GUI's only network action."""

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


@dataclass(frozen=True)
class PullResult:
    ok: bool
    message: str
    detail: str = ""
    returncode: int | None = None  # git's exit code, None when git did not run to the end


def can_pull(data_dir: Path) -> bool:
    return (data_dir / ".git").exists()


def run_pull(data_dir: Path, git: str = "git", timeout: float = 300) -> PullResult:
    """Never raises. A failed fast-forward pull leaves the working tree as it was."""
    if not can_pull(data_dir):
        return PullResult(False, NOT_A_CLONE)
    try:
        proc = subprocess.run(
            [git, "-C", str(data_dir), "pull", "--ff-only"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},  # never wait for a password prompt
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired:
        return PullResult(False, NO_GIT, "git timed out")
    except OSError as exc:
        return PullResult(False, NO_GIT, str(exc))
    detail = "\n".join(s for s in (proc.stdout.strip(), proc.stderr.strip()) if s)
    if proc.returncode != 0:
        return PullResult(False, FAILED, detail, proc.returncode)
    return PullResult(True, PULLED, detail, 0)
