# PyInstaller spec for the Windows GUI build: one windowed Coppertrail.exe.
#
#     uv run python scripts/build_exe.py      (wraps: uv run pyinstaller packaging/coppertrail.spec)
#
# Bundles the code and `coppertrail/ui/web/` (HTML/CSS/JS, vendored uPlot, fonts, icons) and
# nothing else: collected market data must never ship (Blizzard API terms). No Qt: the Qt
# bindings are excluded outright and pywebview only gets its Windows backends.
# ruff: noqa

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
WEB = ROOT / "coppertrail" / "ui" / "web"
ICON = ROOT / "packaging" / "coppertrail.ico"

QT = ["PySide2", "PySide6", "PyQt5", "PyQt6", "qtpy", "pyqtgraph", "webview.platforms.qt"]
UNUSED = ["tkinter", "pyarrow.tests", "pandas.tests", "numpy.tests", "webview.platforms.gtk", "webview.platforms.cocoa", "webview.platforms.cef"]

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    datas=[(str(WEB), "coppertrail/ui/web")],
    hiddenimports=[
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "clr",
    ],
    excludes=QT + UNUSED,
    noarchive=False,
)
# Libraries' own test fixtures (pyarrow ships sample .parquet files) stay out of the bundle.
a.datas = [d for d in a.datas if "/tests/" not in d[0].replace("\\", "/")]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Coppertrail",
    # A window app: no console behind it. COPPERTRAIL_CONSOLE=1 (build_exe.py --console) keeps
    # one, so Python errors and pywebview's log are visible while debugging the build.
    console=os.environ.get("COPPERTRAIL_CONSOLE") == "1",
    upx=False,
    icon=str(ICON) if ICON.exists() else None,
)
