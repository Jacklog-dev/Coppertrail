"""pyqtgraph styling from tokens (HANDOVER 8b "Charts in pyqtgraph").

Views build plots with these helpers so line widths, dashes, fills and axes stay uniform.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QPen

from coppertrail.ui import format as fmt
from coppertrail.ui import theme, tokens

LINE_WIDTH = {
    "primary": tokens.CHART["line_primary"],
    "secondary": tokens.CHART["line_secondary"],
    "tertiary": tokens.CHART["line_tertiary"],
}


def pen(token: str, width: float = 1.0, dash: Sequence[float] | None = None) -> QPen:
    p = pg.mkPen(theme.color(token), width=width)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setCosmetic(True)
    if dash:
        p.setDashPattern(list(dash))
    return p


def series_pen(token: str, weight: str = "primary") -> QPen:
    return pen(token, LINE_WIDTH[weight])


def _spec_pen(key: str) -> QPen:
    token, width, dash = tokens.CHART[key]
    return pen(token, width, None if dash == "solid" else dash)


class CoinAxis(pg.AxisItem):
    """Y axis for prices in copper, labelled with letters: `8g`, `1g 50s`, `80s`."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802 (pyqtgraph API)
        return [fmt.coins_text(max(0, round(v))) for v in values]


def style_plot(plot: pg.PlotItem) -> pg.PlotItem:
    """Axis pens in `border`, tick text `text3` 12 px, horizontal grid only, no menu."""
    tick_font = theme.font("small", px=tokens.CHART["axis_font_px"])
    for name in ("left", "bottom"):
        axis = plot.getAxis(name)
        axis.setPen(pen("border"))
        axis.setTextPen(pen("text3"))
        axis.setTickFont(tick_font)
        axis.setStyle(tickLength=0, tickTextOffset=6)
    plot.showGrid(x=False, y=True)
    left = plot.getAxis("left")
    left.setGrid(255)  # full alpha: the grid colour itself is already subtle
    left.setPen(_spec_pen("grid"))  # pyqtgraph draws grid lines with the axis pen
    left.setTextPen(pen("text3"))
    plot.setMenuEnabled(False)
    plot.hideButtons()
    plot.getViewBox().setDefaultPadding(0.02)
    return plot


def plot_widget(axis_items: dict[str, pg.AxisItem] | None = None) -> pg.PlotWidget:
    w = pg.PlotWidget(axisItems=axis_items or {})
    w.setBackground(theme.color("surface"))
    style_plot(w.getPlotItem())
    return w


def reference_line(plot: pg.PlotItem, y: float, label: str = "") -> pg.InfiniteLine:
    """Dashed baseline (index 100, vendor floor) with an optional label in text3."""
    line = pg.InfiniteLine(pos=y, angle=0, pen=_spec_pen("reference"), movable=False)
    if label:
        line.label = pg.InfLineLabel(
            line, label, position=0.98, anchors=[(1, 1), (1, 1)], color=theme.color("text3")
        )
        line.label.setFont(theme.font("small"))
    plot.addItem(line, ignoreBounds=True)
    return line


def area(
    plot: pg.PlotItem,
    x: np.ndarray,
    y: np.ndarray,
    token: str,
    weight: str = "primary",
    floor: float | None = None,
) -> pg.PlotDataItem:
    """Line plus a 12 % fill down to `floor` (default: the lowest value)."""
    curve = plot.plot(x, y, pen=series_pen(token, weight))
    base = float(np.nanmin(y)) if floor is None else floor
    curve.setFillLevel(base)
    curve.setBrush(theme.color(token, tokens.CHART["area_alpha"]))
    return curve


def band(
    plot: pg.PlotItem, upper: pg.PlotDataItem, lower: pg.PlotDataItem, token: str
) -> pg.FillBetweenItem:
    fill = pg.FillBetweenItem(upper, lower, brush=theme.color(token, tokens.CHART["band_alpha"]))
    plot.addItem(fill)
    fill.setZValue(-1)
    return fill


def bars(
    plot: pg.PlotItem, x: np.ndarray, heights: np.ndarray, token: str | Sequence[str] = "s6"
) -> pg.BarGraphItem:
    """Bars with the 28 % gap; `token` may be one token or one per bar."""
    step = float(np.min(np.diff(x))) if len(x) > 1 else 1.0
    tokens_ = [token] * len(x) if isinstance(token, str) else list(token)
    item = pg.BarGraphItem(
        x=x,
        height=heights,
        width=step * (1 - tokens.CHART["bar_gap"]),
        brushes=[theme.color(t) for t in tokens_],
        pens=[pg.mkPen(None)] * len(x),
    )
    plot.addItem(item)
    return item


def hover_dot(token: str) -> pg.ScatterPlotItem:
    """8 px dot with a 2 px `surface` ring, for crosshair hover points."""
    return pg.ScatterPlotItem(
        size=tokens.CHART["marker_dot_px"],
        brush=theme.color(token),
        pen=pg.mkPen(theme.color("surface"), width=2),
    )


class Crosshair:
    """Vertical and horizontal dashed `text3` lines that follow the mouse, plus hover dots."""

    def __init__(self, plot: pg.PlotItem, curves: list[tuple[pg.PlotDataItem, str]]) -> None:
        self.plot = plot
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=_spec_pen("crosshair"))
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=_spec_pen("crosshair"))
        self.curves = curves
        self.dots = [hover_dot(token) for _, token in curves]
        for item in (self.vline, self.hline, *self.dots):
            plot.addItem(item, ignoreBounds=True)
            item.hide()
        self._proxy = pg.SignalProxy(plot.scene().sigMouseMoved, rateLimit=60, slot=self._moved)

    def place(self, x: float) -> None:
        """Snap to the nearest sample at `x` and show lines and dots there."""
        xs, ys = self.curves[0][0].getData()
        if xs is None or not len(xs):
            return
        i = int(np.clip(np.searchsorted(xs, x), 0, len(xs) - 1))
        self.vline.setPos(xs[i])
        self.hline.setPos(ys[i])
        for dot, (curve, _) in zip(self.dots, self.curves, strict=True):
            cx, cy = curve.getData()
            dot.setData([cx[i]], [cy[i]])
        for item in (self.vline, self.hline, *self.dots):
            item.show()

    def _moved(self, event) -> None:
        pos = event[0]
        vb = self.plot.getViewBox()
        if not self.plot.sceneBoundingRect().contains(pos):
            return
        self.place(vb.mapSceneToView(pos).x())
