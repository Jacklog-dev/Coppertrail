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
# Never in the bundle: AHledger data may not be redistributed. Qt must not be in it either.
FORBIDDEN_SUFFIXES = (".parquet", ".duckdb", ".duckdb.wal")
FORBIDDEN_NAMES = ("pyside", "pyqt", "qtpy", "pyqtgraph", "qt5core", "qt6core")
REQUIRED = ("coppertrail/ui/web/index.html", "coppertrail/ui/web/vendor/")


def bundle_entries(exe: Path) -> list[str]:
    from PyInstaller.archive.readers import CArchiveReader

    return sorted(CArchiveReader(str(exe)).toc)


def check_bundle(names: list[str]) -> list[str]:
    """Problems with a bundle's table of contents; empty when it is fine."""
    lower = [n.replace("\\", "/").lower() for n in names]
    problems = [
        f"collected data in the bundle: {n}" for n in lower if n.endswith(FORBIDDEN_SUFFIXES)
    ]
    problems += [f"Qt in the bundle: {n}" for n in lower if any(q in n for q in FORBIDDEN_NAMES)]
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
    problems = check_bundle(bundle_entries(EXE))
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        EXE.unlink(missing_ok=True)
        return 1
    print(f"Built {EXE} ({EXE.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
