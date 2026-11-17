"""Theme checks that run headless (Qt offscreen platform)."""

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QFontMetricsF, QRawFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from coppertrail.ui import theme, tokens  # noqa: E402

UI_DIR = Path(theme.__file__).parent


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    theme.apply_theme(qapp)
    return qapp


@pytest.mark.parametrize("tok", [tokens.DARK, tokens.LIGHT], ids=["dark", "light"])
def test_stylesheet_fills_every_placeholder(tok):
    qss = theme.stylesheet(tok)
    assert "{" in qss  # literal QSS braces survive
    assert not re.search(r"\{[A-Za-z]\w*\}", qss), "unfilled token placeholder"
    assert tok["accent"] in qss


def test_light_and_dark_define_the_same_tokens():
    assert set(tokens.DARK) == set(tokens.LIGHT)


def test_bundled_fonts_load(app):
    families = theme.load_fonts()
    assert tokens.FONT_UI in families
    assert tokens.FONT_DISPLAY in families
    for name in ("OFL-Caudex.txt", "OFL-Almendra.txt"):
        assert (UI_DIR / "fonts" / name).is_file(), "ship the OFL licence with the fonts"


def test_caudex_regular_digits_are_tabular(app):
    m = QFontMetricsF(theme.font("body", px=200))
    widths = {round(m.horizontalAdvance(d), 2) for d in "0123456789"}
    assert len(widths) == 1, f"digit widths differ: {widths}"


def test_display_roles_are_almendra_uppercase(app):
    from PySide6.QtGui import QFont

    for role in ("h1", "title"):
        f = theme.font(role)
        assert f.family() == tokens.FONT_DISPLAY
        assert f.capitalization() == QFont.Capitalization.AllUppercase
    for role in ("display", "h2", "kpi", "body", "th", "sub", "small"):
        assert theme.font(role).family() == tokens.FONT_UI


def test_ui_font_lacks_triangles_so_dots_are_painted():
    # Documents why widgets.Dot exists and ▲/▼ rely on the system fallback font.
    raw = QRawFont(str(UI_DIR / "fonts" / "Caudex-Regular.ttf"), 14)
    assert raw.supportsCharacter(0x2212)  # real minus sign is in Caudex
    assert not raw.supportsCharacter(0x25CF)


def test_every_icon_renders(app):
    for svg in (UI_DIR / "icons").glob("*.svg"):
        if svg.stem.startswith("app"):
            continue
        assert "currentColor" in svg.read_text(encoding="utf-8"), svg.name
        assert not theme.icon_pixmap(svg.stem, "accent", 18).isNull()
    assert not theme.app_icon().isNull()


def test_widget_code_has_no_hard_coded_colours_or_fonts():
    """HANDOVER 8b: colours and font names come from tokens.py and theme.qss only."""
    hex_colour = re.compile(r"#[0-9A-Fa-f]{6}\b")
    font_names = re.compile(r"[\"'](Caudex|Almendra|Friz Quadrata|Arial|Segoe UI)[\"']")
    for path in UI_DIR.glob("*.py"):
        if path.name == "tokens.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert not hex_colour.search(text), f"hex colour in {path.name}"
        assert not font_names.search(text), f"font name in {path.name}"


def test_style_sample_builds_and_renders(app, tmp_path):
    from coppertrail.ui import sample

    out = tmp_path / "sample.png"
    assert sample.main(["--screenshot", str(out), "--width", "1440"]) == 0
    assert out.stat().st_size > 10_000
