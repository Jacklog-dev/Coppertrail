"""The Windows .exe build: frozen paths, and the bundle check that keeps data and Qt out."""

import importlib.util
import sys
from pathlib import Path

from coppertrail.query import catalog
from coppertrail.ui import devserver

ROOT = Path(__file__).resolve().parents[1]


def _build_script():
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "scripts" / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_web_dir_from_source():
    assert devserver.web_dir() == Path(devserver.__file__).parent / "web"
    assert (devserver.web_dir() / "index.html").is_file()


def test_web_dir_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert devserver.web_dir() == tmp_path / "coppertrail" / "ui" / "web"


def test_default_data_dir_from_source(monkeypatch):
    monkeypatch.delenv("COPPERTRAIL_DATA", raising=False)
    assert catalog.default_data_dir() == Path("private")


def test_default_data_dir_when_frozen_is_next_to_the_exe(monkeypatch, tmp_path):
    monkeypatch.delenv("COPPERTRAIL_DATA", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Coppertrail.exe"))
    assert catalog.default_data_dir() == tmp_path.resolve() / "private"


def test_env_data_dir_wins_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setenv("COPPERTRAIL_DATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert catalog.default_data_dir() == tmp_path


GOOD = [
    "coppertrail\\ui\\web\\index.html",
    "coppertrail\\ui\\web\\vendor\\uPlot.iife.min.js",
    "webview\\lib\\Microsoft.Web.WebView2.Core.dll",
]


def test_bundle_check_passes_a_clean_bundle():
    assert _build_script().check_bundle(GOOD) == []


def test_bundle_check_rejects_data_qt_and_a_missing_front_end():
    check = _build_script().check_bundle
    assert any("collected data" in p for p in check([*GOOD, "hourly/2026-11-16.parquet"]))
    assert any("Qt" in p for p in check([*GOOD, "PySide6\\Qt6Core.dll"]))
    assert any("missing" in p for p in check(GOOD[2:]))


def test_spec_bundles_only_the_web_front_end():
    spec = (ROOT / "packaging" / "coppertrail.spec").read_text(encoding="utf-8")
    assert 'datas=[(str(WEB), "coppertrail/ui/web")]' in spec
    assert "private" not in spec
    assert 'gui="qt"' not in spec
