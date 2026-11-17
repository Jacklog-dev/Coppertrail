"""Filter-bar building blocks: field buttons, segmented control, popovers."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from coppertrail.ui import theme, tokens


class FieldButton(QPushButton):
    """A control button showing `[icon] Caption  Value [chevron]` (caption in text3).

    QPushButton cannot mix text colours, so the parts are child labels that let
    mouse events through to the button.
    """

    def __init__(
        self,
        caption: str = "",
        icon: str | None = None,
        chevron: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "field")
        self.setFixedHeight(tokens.SIZES["control_h"])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(6)
        self._icon_name = icon
        self._icon = QLabel()
        if icon:
            self._icon.setPixmap(theme.icon_pixmap(icon, "text2", 16, 2.0))
            lay.addWidget(self._icon)
        self._caption = QLabel(caption)
        self._caption.setProperty("role", "label")
        self._caption.setFont(theme.font("body"))
        if caption:
            lay.addWidget(self._caption)
        self._value = QLabel()
        self._value.setFont(theme.font("body"))
        lay.addWidget(self._value)
        lay.addStretch(1)
        if chevron:
            ch = QLabel()
            ch.setPixmap(theme.icon_pixmap("chevron", "text3", 14, 2.0))
            lay.addWidget(ch)
        for i in range(lay.count()):
            item = lay.itemAt(i).widget()
            if item:
                item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_value(self, text: str) -> None:
        self._value.setText(text)
        self.setToolTip(text)
        self.updateGeometry()

    def set_active(self, active: bool) -> None:
        theme.set_filter_active(self, active)
        if self._icon_name:
            self._icon.setPixmap(
                theme.icon_pixmap(self._icon_name, "accent" if active else "text2", 16, 2.0)
            )

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(self.layout().sizeHint().width(), tokens.SIZES["control_h"])


class Segmented(QWidget):
    """A row of checkable buttons with exactly one checked (24 h / 7 d / 30 d / All)."""

    changed = Signal(str)

    def __init__(self, options: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)  # lets set_value("") uncheck all (custom range)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in options:
            b = QPushButton(text)
            b.setProperty("role", "segment")
            b.setCheckable(True)
            b.setFixedHeight(tokens.SIZES["control_h"])
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._clicked(k))
            self._group.addButton(b)
            self._buttons[key] = b
            lay.addWidget(b)

    def _clicked(self, key: str) -> None:
        self.set_value(key)
        self.changed.emit(key)

    def set_value(self, key: str) -> None:
        for k, b in self._buttons.items():
            b.setChecked(k == key)

    def value(self) -> str:
        return next((k for k, b in self._buttons.items() if b.isChecked()), "")


class Popover(QFrame):
    """A frameless popup on the `overlay` surface, shown 4 px below its anchor control."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None, width: int = 320) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setProperty("role", "popover")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(width)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 12, 12, 12)
        self.body.setSpacing(tokens.SPACE[1])

    def show_below(self, anchor: QWidget) -> None:
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        screen = anchor.screen().availableGeometry()
        x = min(pos.x(), screen.right() - self.width())
        self.move(max(screen.left(), x), pos.y())
        self.show()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self.closed.emit()


def hline() -> QFrame:
    f = QFrame()
    f.setProperty("role", "rule")
    return f
