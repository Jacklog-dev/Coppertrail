"""Small themed building blocks shared by all views: cards, coin values, changes, legends."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from coppertrail.ui import format as fmt
from coppertrail.ui import theme, tokens

_COIN_TOKENS = {
    "g": ("gold", "goldRing"),
    "s": ("silver", "silverRing"),
    "c": ("copper", "copperRing"),
}
UNIT_SPACE = 6  # px between "12●" and "67●": one word space at body size


def coins_width(copper: int, font: QFont) -> float:
    m = QFontMetricsF(font)
    parts = fmt.coin_parts(copper)
    mark, gap = tokens.COIN["mark_px"], tokens.COIN["gap_px"]
    text = sum(m.horizontalAdvance(f"{n:,}") for n, _ in parts)
    return text + len(parts) * (gap + mark) + (len(parts) - 1) * UNIT_SPACE


def paint_coins(
    painter: QPainter,
    rect: QRectF,
    copper: int,
    font: QFont,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
) -> None:
    """Draw `12● 67● 5●`: number in text1, a 7 px coin mark with a 1 px darker ring.

    The number itself is never coloured in coin colours (HANDOVER 8b).
    """
    m = QFontMetricsF(font)
    mark, gap, ring = tokens.COIN["mark_px"], tokens.COIN["gap_px"], tokens.COIN["ring_px"]
    width = coins_width(copper, font)
    x = rect.left()
    if align & Qt.AlignmentFlag.AlignRight:
        x = rect.right() - width
    elif align & Qt.AlignmentFlag.AlignHCenter:
        x = rect.left() + (rect.width() - width) / 2
    baseline = rect.top() + (rect.height() + m.ascent() - m.descent()) / 2
    # Centre the mark on the digits' x-height band, not the full line box.
    mark_cy = baseline - m.capHeight() / 2

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(font)
    for i, (n, unit) in enumerate(fmt.coin_parts(copper)):
        if i:
            x += UNIT_SPACE
        text = f"{n:,}"
        painter.setPen(theme.color("text1"))
        painter.drawText(QPointF(x, baseline), text)
        x += m.horizontalAdvance(text) + gap
        fill, edge = _COIN_TOKENS[unit]
        painter.setPen(QPen(theme.color(edge), ring))
        painter.setBrush(theme.color(fill))
        r = (mark - ring) / 2
        painter.drawEllipse(QPointF(x + mark / 2, mark_cy), r, r)
        x += mark
    painter.restore()


class CoinLabel(QWidget):
    """A price shown with coin marks. Use for tiles and single values."""

    def __init__(
        self,
        copper: int = 0,
        font_role: str = "body",
        parent: QWidget | None = None,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    ) -> None:
        super().__init__(parent)
        self._copper = copper
        self._align = align
        self.setFont(theme.font(font_role))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_value(self, copper: int) -> None:
        self._copper = copper
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        m = QFontMetricsF(self.font())
        return QSize(int(coins_width(self._copper, self.font())) + 2, int(m.height()) + 2)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        paint_coins(p, QRectF(self.rect()), self._copper, self.font(), self._align)
        p.end()


class CoinDelegate(QStyledItemDelegate):
    """Table delegate painting an int copper value (Qt.UserRole) with coin marks, right-aligned."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        value = index.data(Qt.ItemDataRole.UserRole)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if value is not None:
            rect = QRectF(QRect(opt.rect).adjusted(10, 0, -10, 0))
            paint_coins(painter, rect, int(value), opt.font, Qt.AlignmentFlag.AlignRight)


class ChangeDelegate(QStyledItemDelegate):
    """Table delegate for a percent change (float in Qt.UserRole): `▲ +14.2 %` in rise/fall.

    Painted here so the rise/fall colour survives row selection, where Qt would
    otherwise switch item text to the highlight colour.
    """

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        value = index.data(Qt.ItemDataRole.UserRole)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if value is None:
            return
        text, direction = fmt.percent_change(float(value))
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(theme.color("text2" if direction == "flat" else direction))
        painter.drawText(
            QRect(opt.rect).adjusted(10, 0, -10, 0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            text,
        )
        painter.restore()


def change_label(pct: float, font_role: str = "body") -> QLabel:
    """`▲ +14.2 %` in rise, `▼ −87 %` in fall, `± 0.0 %` in text2: arrow, sign and colour."""
    text, direction = fmt.percent_change(pct)
    lab = QLabel(text)
    theme.set_role(lab, {"rise": "rise", "fall": "fall"}.get(direction, "secondary"), font_role)
    return lab


def label(text: str, role: str = "", font_role: str | None = None) -> QLabel:
    lab = QLabel(text)
    if role:
        theme.set_role(lab, role, font_role)
    elif font_role:
        lab.setFont(theme.font(font_role))
    return lab


class Card(QFrame):
    """A panel: flat `surface`, one 1 px border, 4 px radius. Title in Almendra, uppercase."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        pad = tokens.SIZES["card_pad"]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(tokens.SPACE[2])
        self.header = QHBoxLayout()
        self.header.setSpacing(tokens.SPACE[1])
        heads = QVBoxLayout()
        heads.setSpacing(2)
        self.title_label = label(title, "cardTitle", "title")
        self.subtitle_label = label(subtitle, "sub", "sub")
        heads.addWidget(self.title_label)
        heads.addWidget(self.subtitle_label)
        self.title_label.setVisible(bool(title))
        self.subtitle_label.setVisible(bool(subtitle))
        self.header.addLayout(heads)
        self.header.addStretch(1)
        outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(tokens.SPACE[2])
        outer.addLayout(self.body, 1)

    def set_subtitle(self, text: str) -> None:
        """Card subtitles are the date range and at most one fact (HANDOVER 8b)."""
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))


class Dot(QWidget):
    """A filled status dot in a token colour (6 px by default), e.g. data fresh / filters active.

    Painted rather than typed: the UI fonts have no U+25CF glyph.
    """

    def __init__(self, token: str, px: int = 6, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._token, self._px = token, px
        self.setFixedSize(px + 2, px + 2)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(self._token))
        p.drawEllipse(QRectF(1, 1, self._px, self._px))
        p.end()


class LegendSwatch(QWidget):
    """A short line swatch for chart legends (a Qt row above the plot, not pg.LegendItem)."""

    def __init__(self, token: str, dashed: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._token, self._dashed = token, dashed
        self.setFixedSize(16, 10)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(theme.color(self._token), 2.25)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if self._dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(1, 5), QPointF(15, 5))
        p.end()


def legend(entries: list[tuple[str, str]]) -> QWidget:
    """Legend row: [(token, label), ...] with line swatches and labels in text2."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(tokens.SPACE[1])
    for token, text in entries:
        lay.addWidget(LegendSwatch(token))
        lay.addWidget(label(text, "legend", "small"))
        lay.addSpacing(tokens.SPACE[1])
    lay.addStretch(1)
    return row
