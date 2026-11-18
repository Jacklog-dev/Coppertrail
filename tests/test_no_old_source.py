"""The old third-party data source is gone: no tracked file names it."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERM = "ah" + "ledger"  # built from parts so this file does not match itself


def test_no_tracked_file_names_the_old_source():
    files = (
        subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        .stdout.decode("utf-8")
        .split("\0")
    )
    hits = []
    for name in filter(None, files):
        path = ROOT / name
        if not path.is_file():
            continue  # deleted in the working tree
        if TERM in name.lower():
            hits.append(name)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary files (fonts, icons)
        if TERM in text.lower():
            hits.append(name)
    assert not hits, f"old source named in: {hits}"
