"""Build the Windows GUI executable: `dist/Coppertrail.exe`.

    uv run python scripts/build_exe.py             # windowed release build
    uv run python scripts/build_exe.py --console   # same, with a console for debugging

Runs PyInstaller on `packaging/coppertrail.spec` (work files in `build/`, both gitignored) and
then checks the bundle: it must contain the web front end and no collected market data.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "coppertrail.spec"
DIST = ROOT / "dist"
EXE = DIST / "Coppertrail.exe"
# Never in the bundle: collected API data may not be redistributed. Qt must not be in it either.
# Data formats anywhere (outside the web folder libraries may ship .json metadata, such as
# pythonnet's Python.Runtime.deps.json, so .json is only refused there).
FORBIDDEN_SUFFIXES = (
    ".parquet", ".duckdb", ".duckdb.wal", ".csv", ".arrow", ".feather", ".xlsx",
)  # fmt: skip
FORBIDDEN_NAMES = ("pyside", "pyqt", "qtpy", "pyqtgraph", "qt5core", "qt6core")
# Pure-Python modules inside the PYZ (lower case prefixes of the dotted names).
FORBIDDEN_MODULES = ("pyside", "pyqt", "qtpy", "pyqtgraph", "webview.platforms.qt")
WEB = "coppertrail/ui/web/"
# The only files the front end folder may bundle (license texts are kept too).
WEB_SUFFIXES = (
    ".html", ".css", ".js", ".mjs", ".svg", ".png", ".ico", ".woff", ".woff2", ".ttf", ".otf",
    ".txt",
)  # fmt: skip
# Exact paths allowed besides those: the item -> icon file id map (numbers, no market data).
WEB_ALLOWED = ("coppertrail/ui/web/icon-map.json",)
REQUIRED = ("coppertrail/ui/web/index.html", "coppertrail/ui/web/vendor/")


def bundle_entries(exe: Path) -> list[str]:
    from PyInstaller.archive.readers import CArchiveReader

    return sorted(CArchiveReader(str(exe)).toc)


def bundle_modules(exe: Path) -> list[str]:
    """Module names inside every embedded PYZ archive (pure-Python code is not in the TOC)."""
    from PyInstaller.archive import readers

    archive = readers.CArchiveReader(str(exe))
    modules: set[str] = set()
    for name, entry in archive.toc.items():
        if entry[-1] == "z":  # PKG_ITEM_PYZ (PyInstaller 6)
            modules.update(archive.open_embedded_archive(name).toc)
    return sorted(modules)


def _web_file_ok(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return name.endswith(WEB_SUFFIXES) or "license" in base or name in WEB_ALLOWED


def check_bundle(names: list[str], modules: list[str] = ()) -> list[str]:
    """Problems with a bundle's table of contents and PYZ modules; empty when it is fine."""
    lower = [n.replace("\\", "/").lower() for n in names]
    problems = [
        f"collected data in the bundle: {n}" for n in lower if n.endswith(FORBIDDEN_SUFFIXES)
    ]
    problems += [
        f"not a front-end file in the web folder: {n}"
        for n in lower
        if n.startswith(WEB) and not n.endswith(FORBIDDEN_SUFFIXES) and not _web_file_ok(n)
    ]
    problems += [f"Qt in the bundle: {n}" for n in lower if any(q in n for q in FORBIDDEN_NAMES)]
    problems += [
        f"Qt module in the bundle: {m}" for m in modules if m.lower().startswith(FORBIDDEN_MODULES)
    ]
    problems += [
        f"missing from the bundle: {r}" for r in REQUIRED if not any(r in n for n in lower)
    ]
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if sys.platform != "win32":
        print("The .exe build runs on Windows only.", file=sys.stderr)
        return 1
    cmd = [
        sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean",
        "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
    ]  # fmt: skip
    env = {**os.environ, "COPPERTRAIL_CONSOLE": "1" if "--console" in args else "0"}
    if subprocess.run(cmd, cwd=ROOT, env=env).returncode != 0:
        return 1
    problems = check_bundle(bundle_entries(EXE), bundle_modules(EXE))
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        EXE.unlink(missing_ok=True)
        return 1
    print(f"Built {EXE} ({EXE.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
