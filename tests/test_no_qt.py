"""Jack does not want Qt in this project: not as a dependency, not as an import."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QT_PACKAGES = {
    "pyside6",
    "pyside6-essentials",
    "pyside6-addons",
    "shiboken6",
    "pyqt5",
    "pyqt6",
    "qtpy",
    "pyqtgraph",
    "pyqt6-webengine",
}


def test_lock_file_has_no_qt():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    names = {p["name"].lower() for p in lock["package"]}
    assert not names & QT_PACKAGES


def test_no_qt_imports_in_package():
    pattern = re.compile(r"^\s*(from|import)\s+(PySide|PyQt|qtpy|pyqtgraph)", re.M)
    for py in (ROOT / "coppertrail").rglob("*.py"):
        assert not pattern.search(py.read_text(encoding="utf-8")), py
