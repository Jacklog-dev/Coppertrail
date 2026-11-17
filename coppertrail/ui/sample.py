"""Style sample window (HANDOVER 9, step 6.1): check fonts, tabular figures and colours.

    uv run python -m coppertrail.ui.sample                 # open the window
    uv run python -m coppertrail.ui.sample --light         # parchment variant
    uv run python -m coppertrail.ui.sample --screenshot out.png

All numbers shown are invented sample values, not market data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from coppertrail.ui import charts, theme, tokens
from coppertrail.ui import format as fmt
from coppertrail.ui.widgets import (
    Card,
    ChangeDelegate,
    CoinDelegate,
    CoinLabel,
    Dot,
    change_label,
    label,
    legend,
)
from coppertrail.ui.window import NavRail, StatusStrip, wordmark

SWATCH_GROUPS = [
    ("Surfaces", ["bg0", "bg1", "surface", "raised", "overlay"]),
    ("Text", ["text1", "text2", "text3", "textDis"]),
    ("Borders and grid", ["border", "borderStrong", "grid", "scroll"]),
    ("Accent", ["accent", "accentHover", "accentPressed", "accentMuted", "accentOn"]),
    ("Data series", tokens.SERIES),
    ("Semantic", ["rise", "fall", "attention", "attentionBg"]),
    (
        "Coins: price values only",
        ["gold", "goldRing", "silver", "silverRing", "copper", "copperRing"],
    ),
]

TYPE_SAMPLES = [
    ("h1", "Market overview"),
    ("title", "Price and supply"),
    ("display", None),  # wordmark
    ("h2", "Rugged Leather 19s 8c"),
    ("kpi", "1,284 · 9,063 · 0.17"),
    ("body", "Rugged Leather · Trade goods · 412 of 1,284 items"),
    ("th", "Item  Lowest buyout  Sales/day"),
    ("sub", "17 Oct – 16 Nov 2026 · 30 d"),
    ("small", "Data as of 16 Nov 2026, 08:42 · Prices from AHledger"),
]


def _hline() -> QFrame:
    f = QFrame()
    f.setProperty("role", "rule")
    return f


def _icon_button(text: str, icon_name: str, role: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setIcon(theme.icon(icon_name, "text2"))
    b.setIconSize(QSize(18, 18))
    if role:
        b.setProperty("role", role)
    return b


def swatch_card() -> Card:
    card = Card("Colours", "Token name and value · dark is the default theme")
    grid = QGridLayout()
    grid.setHorizontalSpacing(tokens.SPACE[3])
    grid.setVerticalSpacing(tokens.SPACE[1])
    tok = theme.palette_tokens()
    for row, (group, names) in enumerate(SWATCH_GROUPS):
        grid.addWidget(label(group, "label", "sub"), row * 2, 0, 1, 6)
        for col, name in enumerate(names):
            cell = QWidget()
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            sw = QFrame()
            sw.setProperty("role", "swatch")
            sw.setFixedHeight(30)
            sw.setStyleSheet(f"background: {tok[name]};")  # sample only: the swatch IS the token
            v.addWidget(sw)
            v.addWidget(label(f"{name}  {tok[name]}", "small", "small"))
            grid.addWidget(cell, row * 2 + 1, col)
    for col in range(6):
        grid.setColumnStretch(col, 1)
    card.body.addLayout(grid)
    return card


def type_card() -> Card:
    card = Card("Typography", "Almendra for h1 and card titles only · Caudex for everything else")
    grid = QGridLayout()
    grid.setHorizontalSpacing(tokens.SPACE[4])
    grid.setVerticalSpacing(tokens.SPACE[2])
    for row, (role, text) in enumerate(TYPE_SAMPLES):
        family, weight, px, upper, spacing = tokens.TYPE[role]
        grid.addWidget(label(role, "label", "sub"), row, 0)
        sample = wordmark(px) if text is None else label(text, "", role)
        grid.addWidget(sample, row, 1)
        spec = f"{family} {weight} · {px} px" + (" · uppercase, +6 %" if upper else "")
        grid.addWidget(label(spec, "small", "small"), row, 2, Qt.AlignmentFlag.AlignRight)
    grid.setColumnStretch(1, 1)
    card.body.addLayout(grid)
    return card


def figures_card() -> Card:
    card = Card("Figures", "Tabular digits · coins · signed changes")
    grid = QGridLayout()
    grid.setHorizontalSpacing(tokens.SPACE[4])
    grid.setVerticalSpacing(tokens.SPACE[1])
    heads = ["Count", "Price", "Change", "Bold digits"]
    for c, h in enumerate(heads):
        grid.addWidget(label(h, "label", "th"), 0, c, Qt.AlignmentFlag.AlignRight)
    rows = [
        (1_111, 126_705, 14.23, "1,111"),
        (8_888, 1_908, -87.4, "8,888"),
        (9_063, 480_000, 0.0, "9,063"),
        (1_610_000, 31_010_000, 488.0, "1,610"),
        (412, 750, -3.2, "4,120"),
    ]
    right = Qt.AlignmentFlag.AlignRight
    bold = theme.font("body")
    bold.setBold(True)
    for r, (n, price, pct, b) in enumerate(rows, start=1):
        grid.addWidget(label(fmt.count(n), "", "body"), r, 0, right)
        grid.addWidget(CoinLabel(price, "body", align=right), r, 1)
        grid.addWidget(change_label(pct), r, 2, right)
        bl = QLabel(b)
        bl.setFont(bold)
        grid.addWidget(bl, r, 3, right)
    card.body.addLayout(grid)
    card.body.addWidget(_hline())
    kpis = QHBoxLayout()
    kpis.setSpacing(tokens.SPACE[4])
    for title, widget in [
        ("Items tracked", label("1,284", "", "kpi")),
        ("Median price · 7 d", CoinLabel(196_705, "kpi")),
        ("Supply · 7 d", change_label(14.2, "kpi")),
    ]:
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(title, "label", "sub"))
        col.addWidget(widget)
        kpis.addLayout(col)
    kpis.addStretch(1)
    card.body.addLayout(kpis)
    card.body.addWidget(
        label(
            "Axis letters: "
            + " · ".join(fmt.coins_text(v) for v in (80_000, 15_000, 8_000, 1_908)),
            "small",
            "small",
        )
    )
    card.body.addStretch(1)
    return card


def controls_card() -> Card:
    card = Card("Controls", "Default, hover in borderStrong, changed filters in copper")
    row1 = QHBoxLayout()
    row1.setSpacing(10)
    groups = _icon_button("Leather chain, Herbs", "chevron")
    theme.set_filter_active(groups, True)
    row1.addWidget(groups)
    edit = QPushButton()
    edit.setIcon(theme.icon("edit"))
    edit.setFixedWidth(32)
    row1.addWidget(edit)
    combo = QComboBox()
    combo.addItems(["All classes", "Trade Goods", "Consumable", "Armor"])
    row1.addWidget(combo)
    search = QLineEdit()
    search.setPlaceholderText("Search items")
    search.addAction(theme.icon("search", "text3"), QLineEdit.ActionPosition.LeadingPosition)
    search.setFixedWidth(220)
    row1.addWidget(search)
    seg = QHBoxLayout()
    seg.setSpacing(0)
    seg_group = QButtonGroup(card)
    for text in ("24 h", "7 d", "30 d", "All"):
        b = QPushButton(text)
        b.setProperty("role", "segment")
        b.setCheckable(True)
        b.setChecked(text == "30 d")
        seg_group.addButton(b)
        seg.addWidget(b)
    row1.addLayout(seg)
    date_btn = _icon_button("17 Oct – 16 Nov 2026", "calendar")
    row1.addWidget(date_btn)
    spin = QSpinBox()
    spin.setRange(0, 100_000)
    spin.setSingleStep(10)
    spin.setValue(50)
    spin.setPrefix("Min sales/day ")
    theme.set_filter_active(spin, True)
    row1.addWidget(spin)
    row1.addStretch(1)
    row1.addWidget(Dot("accent"))
    row1.addWidget(label("3 filters active", "accent", "body"))
    reset = QPushButton("Reset")
    reset.setProperty("role", "ghost")
    row1.addWidget(reset)
    card.body.addLayout(row1)

    row2 = QHBoxLayout()
    row2.setSpacing(10)
    primary = _icon_button("Pull latest data", "download", "primary")
    primary.setIcon(theme.icon("download", "accentOn"))
    row2.addWidget(primary)
    row2.addWidget(QPushButton("Default"))
    disabled = QPushButton("Disabled")
    disabled.setEnabled(False)
    row2.addWidget(disabled)
    ghost = QPushButton("Show log")
    ghost.setProperty("role", "ghost")
    row2.addWidget(ghost)
    link = QPushButton("All movers and outliers →")
    link.setProperty("role", "link")
    row2.addWidget(link)
    cb = QCheckBox("Leather chain")
    cb.setChecked(True)
    row2.addWidget(cb)
    row2.addWidget(QCheckBox("Herbs"))
    row2.addWidget(label("needs data", "chip", "small"))
    row2.addWidget(label("spread 18.4 %", "chip", "small"))
    row2.addStretch(1)
    card.body.addLayout(row2)

    tabs = QTabBar()
    tabs.setDrawBase(False)
    tabs.setExpanding(False)
    for t in ("Daily rhythm", "Processing spreads", "Supply shocks", "Weekend effect", "Reset day"):
        tabs.addTab(t)
    tabs.setFont(theme.font("body"))
    card.body.addWidget(tabs)

    prog = QHBoxLayout()
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(62)
    bar.setTextVisible(False)
    prog.addWidget(bar, 1)
    prog.addWidget(label("Reading 142 days · 1,284 items… 62 %", "label", "sub"))
    card.body.addLayout(prog)
    return card


def _sample_series() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    days = np.arange(31, dtype=float)
    scarce = 100 + 14 * (1 - np.exp(-days / 12)) + 2.5 * np.sin(days / 2.2)
    farm = 100 - 9 * (1 - np.exp(-days / 15)) + 2.0 * np.sin(days / 3.1 + 1)
    return days, scarce, farm


def chart_card() -> Card:
    card = Card(
        "Price index, farmable vs scarce goods", "17 Oct – 16 Nov 2026 · 30 d · 100 = 17 Oct"
    )
    zoom = QPushButton()
    zoom.setIcon(theme.icon("zoom"))
    zoom.setFixedWidth(32)
    reset = QPushButton()
    reset.setIcon(theme.icon("reset"))
    reset.setFixedWidth(32)
    card.header.addWidget(zoom)
    card.header.addWidget(reset)
    card.body.addWidget(legend([("s1", "Scarce goods"), ("s2", "Farmable goods")]))
    pw = charts.plot_widget()
    pw.setFixedHeight(300)
    plot = pw.getPlotItem()
    days, scarce, farm = _sample_series()
    c1 = charts.area(plot, days, scarce, "s1", floor=float(min(farm.min(), scarce.min())) - 2)
    c2 = plot.plot(days, farm, pen=charts.series_pen("s2", "secondary"))
    charts.reference_line(plot, 100, "100")
    cross = charts.Crosshair(plot, [(c1, "s1"), (c2, "s2")])
    cross.place(21)
    plot.getAxis("bottom").setTicks(
        [
            [
                (d, lab)
                for d, lab in [
                    (0, "17 Oct"),
                    (7, "24 Oct"),
                    (14, "31 Oct"),
                    (21, "7 Nov"),
                    (30, "16 Nov"),
                ]
            ]
        ]
    )
    card.body.addWidget(pw)
    return card


def hour_card() -> Card:
    card = Card("Hour-of-day profile", "10 – 16 Nov 2026 · 7 d · 100 = daily mean")
    pw = charts.plot_widget()
    pw.setFixedHeight(220)
    plot = pw.getPlotItem()
    hours = np.arange(24, dtype=float)
    idx = 100 + 7 * np.sin((hours - 13) / 24 * 2 * np.pi)
    cheap, dear = int(np.argmin(idx)), int(np.argmax(idx))
    colours = ["s6"] * 24
    colours[cheap], colours[dear] = "rise", "fall"
    charts.bars(plot, hours, idx - 90, colours)
    plot.getAxis("left").setTicks([[(v - 90, str(v)) for v in (90, 95, 100, 105, 110)]])
    plot.getAxis("bottom").setTicks([[(h, f"{h:02d}") for h in range(0, 24, 3)]])
    charts.reference_line(plot, 10)
    card.body.addWidget(pw)
    notes = QHBoxLayout()
    notes.addWidget(label(f"▼ cheapest {cheap:02d}:00", "rise", "small"))
    notes.addWidget(label(f"▲ dearest {dear:02d}:00", "fall", "small"))
    notes.addStretch(1)
    notes.addWidget(label("spread 14.0 %", "chip", "small"))
    card.body.addLayout(notes)
    card.body.addStretch(1)
    return card


def table_card() -> Card:
    card = Card("Biggest risers", "Last 7 days · sample values")
    rows = [
        ("Waylaid Crates", 1_908, 488.0, 52.0, 214),
        ("Woolen Bag", 19_800, 171.0, -12.0, 96),
        ("Gold Ore", 126_705, 14.2, 3.1, 412),
        ("Rugged Leather", 1_900, -3.6, 80.0, 1_284),
        ("Devilsaur Leather", 31_010_000, -87.0, 140.0, 38),
    ]
    t = QTableWidget(len(rows), 5)
    t.setProperty("role", "data")
    t.setHorizontalHeaderLabels(
        ["Item", "Lowest buyout", "Price change", "Supply change", "Sales/day"]
    )
    t.verticalHeader().hide()
    t.setShowGrid(False)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    t.verticalHeader().setDefaultSectionSize(tokens.SIZES["row_h"])
    t.setItemDelegateForColumn(1, CoinDelegate(t))
    t.setItemDelegateForColumn(2, ChangeDelegate(t))
    t.setItemDelegateForColumn(3, ChangeDelegate(t))
    hh = t.horizontalHeader()
    hh.setFont(theme.font("th"))
    hh.setHighlightSections(False)
    hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for c in range(1, 5):
        hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        t.horizontalHeaderItem(c).setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
    right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    for r, (name, price, pc, sc, sales) in enumerate(rows):
        t.setItem(r, 0, QTableWidgetItem(name))
        price_item = QTableWidgetItem()
        price_item.setData(Qt.ItemDataRole.UserRole, price)
        t.setItem(r, 1, price_item)
        for c, pct in ((2, pc), (3, sc)):
            it = QTableWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, pct)
            t.setItem(r, c, it)
        it = QTableWidgetItem(fmt.thousands(sales))
        it.setTextAlignment(right)
        t.setItem(r, 4, it)
    t.selectRow(2)
    t.setFixedHeight(tokens.SIZES["row_h"] * (len(rows) + 1) + 4)
    card.body.addWidget(t)
    card.body.addStretch(1)
    return card


def build_content() -> QWidget:
    content = QWidget()
    content.setObjectName("View")
    pad, gap = tokens.SIZES["view_pad"], tokens.SIZES["gap"]
    v = QVBoxLayout(content)
    v.setContentsMargins(pad, pad, pad, pad)
    v.setSpacing(gap)
    head = QVBoxLayout()
    head.setSpacing(2)
    head.addWidget(label("Style sample", "h1", "h1"))
    head.addWidget(
        label(
            "Fonts, figures and colours from tokens.py · all values are invented sample data",
            "sub",
            "sub",
        )
    )
    v.addLayout(head)
    v.addWidget(controls_card())
    row = QHBoxLayout()
    row.setSpacing(gap)
    row.addWidget(type_card(), 3)
    row.addWidget(figures_card(), 2)
    v.addLayout(row)
    row = QHBoxLayout()
    row.setSpacing(gap)
    row.addWidget(chart_card(), 2)
    row.addWidget(hour_card(), 1)
    v.addLayout(row)
    row = QHBoxLayout()
    row.setSpacing(gap)
    row.addWidget(table_card(), 1)
    row.addWidget(swatch_card(), 1)
    v.addLayout(row)
    v.addStretch(1)
    return content


class SampleWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Coppertrail · style sample")
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(NavRail())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = build_content()
        scroll.setWidget(self.content)
        body.addWidget(scroll, 1)
        outer.addLayout(body, 1)
        strip = StatusStrip()
        strip.text.setText("Data as of 16 Nov 2026, 08:42")
        strip.dot_stale.hide()
        outer.addWidget(strip)
        self.setCentralWidget(central)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--light", action="store_true", help="parchment (light) tokens")
    parser.add_argument("--screenshot", type=Path, help="render the full window to a PNG and exit")
    parser.add_argument("--width", type=int, default=1920)
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    theme.apply_theme(app, tokens.LIGHT if args.light else tokens.DARK)
    win = SampleWindow()
    if args.screenshot:
        # Render without putting the window on screen, so it may be taller than the display.
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.resize(args.width, 1080)
        win.show()
        app.processEvents()
        # Grow the window to the full content height so one image shows everything.
        full = win.content.sizeHint().height() + tokens.SIZES["status_h"]
        win.resize(args.width, max(1080, full))
        app.processEvents()
        win.grab().save(str(args.screenshot))
        print(f"wrote {args.screenshot}")
        return 0
    win.resize(1600, 1000)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
