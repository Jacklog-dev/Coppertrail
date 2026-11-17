"""Screenshots of the web front end with headless Microsoft Edge (ships with Windows 11)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def find_edge() -> Path | None:
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        if base:
            exe = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if exe.is_file():
                return exe
    found = shutil.which("msedge") or shutil.which("microsoft-edge")
    return Path(found) if found else None


def edge_command(edge: Path, url: str, out: Path, size: tuple[int, int]) -> list[str]:
    w, h = size
    return [
        str(edge),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        f"--window-size={w},{h}",
        "--virtual-time-budget=5000",  # let the page fetch its state and render
        f"--screenshot={out}",
        url,
    ]


def take(url: str, out: Path, size: tuple[int, int]) -> int:
    edge = find_edge()
    if edge is None:
        print("Microsoft Edge not found")
        return 1
    out = out.resolve()
    proc = subprocess.run(edge_command(edge, url, out, size), capture_output=True, timeout=120)
    if proc.returncode == 0 and out.is_file():
        print(f"wrote {out}")
        return 0
    print(proc.stderr.decode("utf-8", "replace").strip() or "screenshot failed")
    return proc.returncode or 1
