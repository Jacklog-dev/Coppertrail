"""Theme: bundled fonts, the QSS template filled from tokens, typed fonts, colours, icons.

Widget code takes every colour, font and size from here (or from `tokens`), never
literals (HANDOVER 8b). Call `apply_theme(app)` once after creating the QApplication.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

from coppertrail.ui import tokens

UI_DIR = Path(__file__).parent
FONT_DIR = UI_DIR / "fonts"
ICON_DIR = UI_DIR / "icons"
QSS_TEMPLATE = UI_DIR / "theme.qss"

_active: dict[str, str] = tokens.DARK


def palette_tokens() -> dict[str, str]:
    """The token set currently applied (DARK unless `apply_theme` got LIGHT)."""
    return _active


def stylesheet(tok: dict[str, str] | None = None) -> str:
    """The QSS template with every `{token}` filled in."""
    return QSS_TEMPLATE.read_text(encoding="utf-8").format_map(tok or _active)


def load_fonts() -> list[str]:
    """Register the bundled .ttf files with Qt; returns the font families found."""
    families: set[str] = set()
    for path in sorted(FONT_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            raise RuntimeError(f"Qt could not load font {path.name}")
        families.update(QFontDatabase.applicationFontFamilies(font_id))
    missing = {tokens.FONT_UI, tokens.FONT_DISPLAY} - families
    if missing:
        raise RuntimeError(f"bundled fonts missing: {', '.join(sorted(missing))}")
    return sorted(families)


def color(name: str, alpha: float = 1.0) -> QColor:
    """A token colour as QColor, optionally with alpha 0..1."""
    c = QColor(_active[name])
    c.setAlphaF(alpha)
    return c


def font(role: str, *, px: int | None = None) -> QFont:
    """A QFont for a TYPE role (h1, title, display, h2, kpi, body, th, sub, small).

    Almendra roles get uppercase and +6 % letter spacing, which QSS cannot do.
    Caudex Regular already has equal-width digits; `tnum` is still requested so
    numbers stay tabular should the font be swapped.
    """
    family, weight, size, upper, spacing = tokens.TYPE[role]
    f = QFont(family)
    f.setPixelSize(px or size)
    f.setWeight(QFont.Weight(weight))
    if upper:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + spacing)
    f.setFeature(QFont.Tag("tnum"), 1)
    f.setFeature(QFont.Tag("lnum"), 1)
    return f


def set_role(widget: QWidget, role: str, font_role: str | None = None) -> QWidget:
    """Set the QSS `role` property and, for roles that need it, the font."""
    widget.setProperty("role", role)
    if font_role:
        widget.setFont(font(font_role))
    return widget


def set_filter_active(widget: QWidget, active: bool) -> None:
    """Toggle the copper "changed from default" look and re-polish (HANDOVER 8b)."""
    widget.setProperty("filterActive", active)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


@cache
def _svg_source(name: str) -> str:
    return (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")


def icon_pixmap(name: str, token: str = "text2", size: int = 18, dpr: float = 1.0) -> QPixmap:
    """Render a stroke icon from `icons/` in a token colour (`currentColor` is replaced)."""
    svg = _svg_source(name).replace("currentColor", _active[token])
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(QSize(round(size * dpr), round(size * dpr)))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, token: str = "text2", *, active: str = "accent", size: int = 18) -> QIcon:
    """A QIcon with the normal state in `token` and checked/selected states in `active`."""
    dpr = 2.0  # render sharp for high-DPI screens, Qt scales down as needed
    ic = QIcon()
    ic.addPixmap(icon_pixmap(name, token, size, dpr), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(icon_pixmap(name, active, size, dpr), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(icon_pixmap(name, active, size, dpr), QIcon.Mode.Selected, QIcon.State.Off)
    ic.addPixmap(icon_pixmap(name, "textDis", size, dpr), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic


def app_icon() -> QIcon:
    """The shield mark: simplified geometry at 16/20 px, full geometry from 24 px."""
    ic = QIcon()
    for size, name in (
        (16, "app-small"),
        (20, "app-small"),
        (24, "app"),
        (32, "app"),
        (48, "app"),
        (256, "app"),
    ):
        renderer = QSvgRenderer(str(ICON_DIR / f"{name}.svg"))
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        ic.addPixmap(pm)
    return ic


def _palette(tok: dict[str, str]) -> QPalette:
    """Palette for what QSS does not reach: links, placeholders, highlight in item views."""
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: "bg1",
        QPalette.ColorRole.WindowText: "text1",
        QPalette.ColorRole.Base: "surface",
        QPalette.ColorRole.AlternateBase: "surface",
        QPalette.ColorRole.Text: "text1",
        QPalette.ColorRole.Button: "raised",
        QPalette.ColorRole.ButtonText: "text1",
        QPalette.ColorRole.ToolTipBase: "overlay",
        QPalette.ColorRole.ToolTipText: "text1",
        QPalette.ColorRole.PlaceholderText: "text3",
        QPalette.ColorRole.Highlight: "accentMuted",
        QPalette.ColorRole.HighlightedText: "text1",
        QPalette.ColorRole.Link: "accent",
        QPalette.ColorRole.LinkVisited: "accent",
        QPalette.ColorRole.BrightText: "text1",
    }
    for role, name in roles.items():
        p.setColor(role, QColor(tok[name]))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(tok["textDis"]))
    return p


def configure_charts(tok: dict[str, str]) -> None:
    """pyqtgraph defaults from HANDOVER 8b "Charts in pyqtgraph"."""
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, background=tok["surface"], foreground=tok["text3"])


def apply_theme(app: QApplication, tok: dict[str, str] | None = None) -> None:
    """Load fonts, set palette, stylesheet, app font and chart defaults."""
    global _active
    _active = tok or tokens.DARK
    load_fonts()
    app.setStyle("Fusion")  # predictable base for QSS on every platform
    app.setPalette(_palette(_active))
    app.setFont(font("body"))
    app.setStyleSheet(stylesheet(_active))
    app.setWindowIcon(app_icon())
    configure_charts(_active)
