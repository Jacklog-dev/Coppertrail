"""Pull latest data, the GUI's only network action.

1. Download the newest copied-data artifact (item details and recipes copied from Blizzard,
   never in git) into a staging folder, with the GitHub CLI (`gh`), which resolves the
   repository from the data folder's git remote and uses the user's own `gh` login.
2. `git pull --ff-only` the data folder (the data repo's `main`: our own conclusions).
3. Only when both worked, replace `<data>/window/` with the staging folder.

So a failed step leaves the data folder as it was. Afterwards, and at every app start,
copied rows older than `copied_days` are pruned locally too (`prune_copied`).

A `window/` left over from the old window-branch layout (a git worktree) is removed, and
its remote-tracking branch and objects are dropped from the local clone.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

from coppertrail.collector.window import ARTIFACT

log_ = logging.getLogger(__name__)

PULLED = "Pulled latest data"
COMMAND = "git pull --ff-only"
NOT_A_CLONE = "The data folder is not a git clone"
FAILED = "Pull failed · the local archive is unchanged"
NO_GIT = "Pull failed · git could not be started"
NO_GH = "Pull failed · the GitHub CLI (gh) could not be started"
DOWNLOAD_FAILED = "Pull failed · the item data could not be downloaded"

WINDOW = "window"  # the copied-data folder inside the data folder (gitignored)
STAGING = ".window-new"
LIST_ARTIFACTS = f"repos/{{owner}}/{{repo}}/actions/artifacts?name={ARTIFACT}&per_page=100"
DEFAULT_COPIED_DAYS = 30


@dataclass(frozen=True)
class PullResult:
    ok: bool
    message: str
    detail: str = ""
    returncode: int | None = None  # the failing tool's exit code, None when it did not run


class _Failed(Exception):
    def __init__(self, result: PullResult):
        self.result = result


def can_pull(data_dir: Path) -> bool:
    return (data_dir / ".git").exists()


def _exec(cmd: list[str], cwd: Path, timeout: float, *, binary: bool = False):
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        **({} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}),
    )


def gh_download(data_dir: Path, gh: str = "gh", timeout: float = 300) -> bytes | None:
    """The newest unexpired copied-data artifact as zip bytes, None when there is none.
    Raises `_Failed` with NO_GH or DOWNLOAD_FAILED."""

    def run(*args: str, binary: bool = False):
        try:
            proc = _exec([gh, *args], data_dir, timeout, binary=binary)
        except subprocess.TimeoutExpired:
            raise _Failed(PullResult(False, DOWNLOAD_FAILED, "gh timed out")) from None
        except OSError as exc:
            raise _Failed(PullResult(False, NO_GH, str(exc))) from None
        if proc.returncode != 0:
            err = (
                proc.stderr
                if isinstance(proc.stderr, str)
                else proc.stderr.decode("utf-8", "replace")
            )
            raise _Failed(PullResult(False, DOWNLOAD_FAILED, err.strip(), proc.returncode))
        return proc.stdout

    listing = json.loads(run("api", LIST_ARTIFACTS) or "{}")
    live = [a for a in listing.get("artifacts", []) if not a.get("expired")]
    if not live:
        return None
    newest = max(live, key=lambda a: a.get("created_at", ""))
    return run("api", f"repos/{{owner}}/{{repo}}/actions/artifacts/{newest['id']}/zip", binary=True)


def unpack(zip_bytes: bytes, target: Path) -> int:
    """Extract only `.parquet` files with safe relative paths. Returns the file count."""
    count = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            name = PurePosixPath(info.filename)
            if info.is_dir() or name.suffix != ".parquet":
                continue
            if name.is_absolute() or ".." in name.parts or ":" in info.filename:
                continue
            dest = target.joinpath(*name.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
            count += 1
    return count


def run_pull(
    data_dir: Path,
    git: str = "git",
    timeout: float = 300,
    download: Callable[[Path], bytes | None] | None = None,
    today: date | None = None,
) -> PullResult:
    """Never raises. A failed step leaves the data folder as it was."""
    if not can_pull(data_dir):
        return PullResult(False, NOT_A_CLONE)
    download = download or gh_download
    log: list[str] = []
    staging = data_dir / STAGING

    def run(*args: str) -> str:
        try:
            proc = _exec([git, "-C", str(data_dir), *args], data_dir, timeout)
        except subprocess.TimeoutExpired:
            raise _Failed(PullResult(False, NO_GIT, "git timed out")) from None
        except OSError as exc:
            raise _Failed(PullResult(False, NO_GIT, str(exc))) from None
        log.extend(s for s in (proc.stdout.strip(), proc.stderr.strip()) if s)
        if proc.returncode != 0:
            raise _Failed(PullResult(False, FAILED, "\n".join(log), proc.returncode))
        return proc.stdout

    try:
        _rmtree(staging)
        zip_bytes = download(data_dir)
        if zip_bytes is not None:
            staging.mkdir()
            n = unpack(zip_bytes, staging)
            log.append(f"copied data: {n} file(s) downloaded")
        else:
            log.append("copied data: no artifact available, window/ kept")
        run("pull", "--ff-only")
        _drop_window_worktree(data_dir, run)
        if zip_bytes is not None:
            _rmtree(data_dir / WINDOW)
            staging.rename(data_dir / WINDOW)
        _exclude(data_dir, f"/{WINDOW}/")
        _exclude(data_dir, f"/{STAGING}/")
    except _Failed as failed:
        _rmtree(staging)
        return failed.result
    except (OSError, zipfile.BadZipFile) as exc:
        _rmtree(staging)
        return PullResult(False, DOWNLOAD_FAILED, f"{type(exc).__name__}: {exc}")
    prune_copied(data_dir, today)
    return PullResult(True, PULLED, "\n".join(log), 0)


def _drop_window_worktree(data_dir: Path, run) -> None:
    """Remove the old layout's window worktree, its branch ref and its objects."""
    window = data_dir / WINDOW
    if (window / ".git").is_file():
        run("worktree", "remove", "--force", WINDOW)
    run("worktree", "prune")
    refs = run("for-each-ref", "--format=%(refname)", "refs/remotes/origin/window").strip()
    if refs:
        run("update-ref", "-d", "refs/remotes/origin/window")
        run("reflog", "expire", "--expire-unreachable=now", "--all")
        run("gc", "--prune=now", "--quiet")


def prune_copied(data_dir: Path, today: date | None = None) -> int:
    """Drop local copied rows older than `copied_days` (from collector.toml, default 30).
    Returns the number of files deleted. Never raises."""
    try:
        from coppertrail.collector.config import load_config
        from coppertrail.collector.store import Store
        from coppertrail.collector.window import prune_window

        window = data_dir / WINDOW
        if not window.is_dir():
            return 0
        try:
            days = load_config(data_dir).retention.copied_days
        except (ValueError, OSError):
            days = DEFAULT_COPIED_DAYS
        today = today or datetime.now(UTC).date()
        return len(prune_window(Store(data_dir, window), today, days))
    except Exception:  # noqa: BLE001
        log_.exception("pruning copied data failed")
        return 0


def _rmtree(path: Path) -> None:
    if not path.exists():
        return

    def force(func, p, _exc):
        os.chmod(p, 0o700)  # git marks pack files read-only on Windows
        func(p)

    shutil.rmtree(path, onexc=force)


def _exclude(data_dir: Path, pattern: str) -> None:
    """Keep a folder out of main's `git status` (local only, never committed)."""
    info = data_dir / ".git" / "info"
    exclude = info / "exclude"
    try:
        lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if pattern not in lines:
            info.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as f:
                f.write(("\n" if lines else "") + pattern + "\n")
    except OSError:
        pass  # cosmetic: main's status shows the folder as untracked, nothing breaks
