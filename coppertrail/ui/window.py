"""Main window frame (HANDOVER 8b "Window frame"): nav rail, filter bar, views, status strip.

The GUI reads the data folder only through `coppertrail.query`. Its one network action is
"Pull latest data", which runs `git pull --ff-only` in the data folder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from coppertrail.query.catalog import (
    ArchiveStatus,
    Item,
    archive_status,
    default_data_dir,
    load_items,
)
from coppertrail.query.filtering import apply_filters, date_window
from coppertrail.query.groups import ItemGroup, load_groups, save_groups
from coppertrail.query.settings import Filters, Settings, load_settings, save_settings
from coppertrail.ui import format as fmt
from coppertrail.ui import theme, tokens
from coppertrail.ui.filterbar import FilterBar
from coppertrail.ui.groupeditor import GroupEditor
from coppertrail.ui.widgets import Card, CoinDelegate, Dot, label

AHLEDGER_URL = "https://ahledger.com"
STALE_AFTER_DAYS = 2
VIEWS = [
    ("Market overview", "overview"),
    ("Item detail", "item"),
    ("Patterns", "patterns"),
    ("Movers && outliers", "movers"),  # && renders a literal & on a button
]
PREVIEW_ROWS = 300


def wordmark(px: int = 17) -> QWidget:
    """Shield mark plus "Copper" in accent and "trail" in text1 (Caudex 700)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(tokens.SPACE[1] + 2)
    mark = QLabel()
    mark.setPixmap(theme.app_icon().pixmap(30, 30))
    lay.addWidget(mark)
    tok = theme.palette_tokens()
    name = QLabel(
        f'<span style="color:{tok["accent"]}">Copper</span>'
        f'<span style="color:{tok["text1"]}">trail</span>'
    )
    name.setFont(theme.font("display", px=px))
    lay.addWidget(name)
    lay.addStretch(1)
    return w


class NavRail(QWidget):
    view_selected = Signal(int)
    data_folder_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(tokens.SIZES["nav_w"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 12)
        lay.setSpacing(4)
        head = QWidget()
        head.setFixedHeight(tokens.SIZES["filterbar_h"])
        hl = QHBoxLayout(head)
        hl.setContentsMargins(4, 0, 0, 0)
        hl.addWidget(wordmark())
        lay.addWidget(head)
        lay.addSpacing(8)
        self.group = QButtonGroup(self)
        self.buttons: list[QPushButton] = []
        for i, (text, ic) in enumerate(VIEWS):
            b = self._nav_button(text, ic)
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.group.addButton(b, i)
            self.buttons.append(b)
            lay.addWidget(b)
        self.group.idClicked.connect(self.view_selected.emit)
        lay.addStretch(1)
        self.data_btn = self._nav_button("Data folder", "folder")
        self.data_btn.clicked.connect(self.data_folder_clicked.emit)
        lay.addWidget(self.data_btn)

    @staticmethod
    def _nav_button(text: str, icon: str) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("role", "nav")
        b.setIcon(theme.icon(icon, "text2"))
        b.setIconSize(QSize(18, 18))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def select(self, index: int) -> None:
        self.buttons[index].setChecked(True)


class StatusStrip(QWidget):
    """Dot + "Data as of …" · Pull latest data · spacer · "Prices from AHledger" (always)."""

    pull_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(tokens.SIZES["status_h"])
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)
        self.dot_fresh, self.dot_stale = Dot("rise"), Dot("attention")
        lay.addWidget(self.dot_fresh)
        lay.addWidget(self.dot_stale)
        self.text = label("", "secondary", "small")
        lay.addWidget(self.text)
        self.pull = QPushButton("Pull latest data")
        self.pull.setProperty("role", "link")
        self.pull.setIcon(theme.icon("download", "accent"))
        self.pull.setFont(theme.font("small"))
        self.pull.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pull.clicked.connect(self.pull_clicked.emit)
        lay.addWidget(self.pull)
        self.error = label("", "fall", "small")
        lay.addWidget(self.error)
        lay.addStretch(1)
        credit = QPushButton("Prices from AHledger")
        credit.setProperty("role", "link")
        credit.setIcon(theme.icon("external", "accent"))
        credit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # icon after the text
        credit.setFont(theme.font("small"))
        credit.setCursor(Qt.CursorShape.PointingHandCursor)
        credit.setToolTip(AHLEDGER_URL)
        credit.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(AHLEDGER_URL)))
        lay.addWidget(credit)

    def set_status(self, status: ArchiveStatus, can_pull: bool) -> None:
        age = status.age_days()
        stale = age is not None and age > STALE_AFTER_DAYS
        self.dot_fresh.setVisible(status.as_of is not None and not stale)
        self.dot_stale.setVisible(stale)
        if status.as_of is None:
            text = "No data yet"
        elif stale:
            text = f"Data is {int(age)} days old · as of {fmt.local_datetime(status.as_of)}"
        else:
            text = f"Data as of {fmt.local_datetime(status.as_of)}"
        self.text.setText(text)
        self.text.setProperty("role", "attention" if stale else "secondary")
        self.text.style().unpolish(self.text)
        self.text.style().polish(self.text)
        self.pull.setEnabled(can_pull)
        self.pull.setToolTip("" if can_pull else "The data folder is not a git clone")

    def set_pulling(self, pulling: bool) -> None:
        self.pull.setText("Pulling…" if pulling else "Pull latest data")
        self.pull.setEnabled(not pulling)
        if pulling:
            self.set_error("")

    def set_error(self, message: str, detail: str = "") -> None:
        self.error.setText(message)
        self.error.setToolTip(detail)


@dataclass
class AppState:
    data_dir: Path
    items: list[Item] = field(default_factory=list)
    groups: list[ItemGroup] = field(default_factory=list)
    status: ArchiveStatus = field(default_factory=lambda: ArchiveStatus(None, None, None))
    filters: Filters = field(default_factory=Filters)


class PreviewView(QWidget):
    """Placeholder for a view not built yet: header, item count and the filtered items.

    The real views (HANDOVER 9, step 6.3) replace these one by one.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("View")
        scroll.setWidget(content)
        pad = tokens.SIZES["view_pad"]
        lay = QVBoxLayout(content)
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(tokens.SIZES["gap"])
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label(title.replace("&&", "&"), "h1", "h1"))
        self.sub = label("", "sub", "sub")
        head.addWidget(self.sub)
        lay.addLayout(head)
        self.card = Card("Items passing the filters")
        self.table = QTableWidget(0, 4)
        self.table.setProperty("role", "data")
        self.table.setHorizontalHeaderLabels(["Item", "Class", "Lowest buyout", "Sales/day"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(tokens.SIZES["row_h"])
        self.table.setItemDelegateForColumn(2, CoinDelegate(self.table))
        hh = self.table.horizontalHeader()
        hh.setFont(theme.font("th"))
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        for c in (2, 3):
            self.table.horizontalHeaderItem(c).setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        self.card.body.addWidget(self.table, 1)
        self.card.setMinimumHeight(480)
        lay.addWidget(self.card, 1)

    def show_items(self, shown: list[Item], total: int, window: str) -> None:
        self.sub.setText(f"{fmt.thousands(len(shown))} of {fmt.thousands(total)} items")
        rows = sorted(shown, key=lambda i: -i.sales_per_day)[:PREVIEW_ROWS]
        more = f" · top {PREVIEW_ROWS} by sales/day" if len(shown) > PREVIEW_ROWS else ""
        self.card.set_subtitle(f"{window} · preview until this view is built{more}")
        self.table.setRowCount(len(rows))
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for r, item in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(item.name))
            cls = QTableWidgetItem(item.item_class)
            cls.setForeground(theme.color("text2"))
            self.table.setItem(r, 1, cls)
            price = QTableWidgetItem()
            price.setData(Qt.ItemDataRole.UserRole, item.min_buyout)
            self.table.setItem(r, 2, price)
            sales = QTableWidgetItem(fmt.count(item.sales_per_day))
            sales.setTextAlignment(right)
            self.table.setItem(r, 3, sales)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings | None = None,
        settings_file: Path | None = None,
        groups_file: Path | None = None,
        data_dir: Path | None = None,
    ) -> None:
        """`data_dir` overrides the saved data folder for this session without saving it."""
        super().__init__()
        self.setWindowTitle("Coppertrail")
        self.setMinimumSize(1280, 800)
        self._settings_file = settings_file
        self._groups_file = groups_file
        self.settings = settings or load_settings(settings_file)
        if data_dir is None:
            data_dir = (
                Path(self.settings.data_dir) if self.settings.data_dir else default_data_dir()
            )
        self.state = AppState(data_dir=data_dir, filters=self.settings.filters)
        self._pull: QProcess | None = None

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = NavRail()
        body.addWidget(self.nav)
        main = QVBoxLayout()
        main.setSpacing(0)
        self.filter_bar = FilterBar()
        main.addWidget(self.filter_bar)
        self.stack = QStackedWidget()
        self.views = [PreviewView(title) for title, _ in VIEWS]
        for v in self.views:
            self.stack.addWidget(v)
        main.addWidget(self.stack, 1)
        body.addLayout(main, 1)
        outer.addLayout(body, 1)
        self.status_strip = StatusStrip()
        outer.addWidget(self.status_strip)
        self.setCentralWidget(central)

        self.nav.view_selected.connect(self.stack.setCurrentIndex)
        self.nav.data_folder_clicked.connect(self.choose_data_folder)
        self.filter_bar.changed.connect(self._filters_changed)
        self.filter_bar.edit_groups_requested.connect(self.edit_groups)
        self.status_strip.pull_clicked.connect(self.pull_latest)
        self.reload()

    # Data ----------------------------------------------------------------------

    def reload(self) -> None:
        st = self.state
        st.items = load_items(st.data_dir) if st.data_dir.is_dir() else []
        st.status = (
            archive_status(st.data_dir) if st.data_dir.is_dir() else ArchiveStatus(None, None, None)
        )
        st.groups = load_groups(self._groups_file)
        self.filter_bar.set_data(st.items, st.groups, st.status)
        self.filter_bar.set_filters(st.filters, emit=False)
        self.status_strip.set_status(st.status, can_pull=(st.data_dir / ".git").exists())
        self.status_strip.setToolTip(str(st.data_dir.resolve()))
        self._refresh_views()

    def _refresh_views(self) -> None:
        st = self.state
        shown = apply_filters(st.items, st.groups, st.filters)
        lo, hi = date_window(st.filters, st.status)
        window = f"{fmt.date_range(lo, hi)} · {(hi - lo).days + 1} d"
        for v in self.views:
            v.show_items(shown, len(st.items), window)

    def _filters_changed(self, filters: Filters) -> None:
        self.state.filters = filters
        self.settings.filters = filters
        save_settings(self.settings, self._settings_file)
        self._refresh_views()

    # Actions -------------------------------------------------------------------

    def edit_groups(self, new_group: bool = False) -> None:
        dlg = GroupEditor(self.state.groups, self.state.items, self, new_group=new_group)
        if not dlg.exec():
            return
        groups = dlg.result_groups()
        save_groups(groups, self._groups_file)
        names = {g.name for g in groups}
        self.state.groups = groups
        self.filter_bar.set_data(self.state.items, groups, self.state.status)
        # Drop selections of groups that were deleted or renamed.
        kept = [n for n in self.state.filters.groups if n in names]
        self.filter_bar.update_filters(groups=kept)

    def choose_data_folder(self) -> None:
        start = str(self.state.data_dir.resolve()) if self.state.data_dir.exists() else ""
        path = QFileDialog.getExistingDirectory(self, "Choose the data folder", start)
        if not path:
            return
        self.state.data_dir = Path(path)
        self.settings.data_dir = path
        save_settings(self.settings, self._settings_file)
        self.reload()

    def pull_latest(self) -> None:
        """`git pull --ff-only` in the data folder: the GUI's only network action."""
        if self._pull is not None:
            return
        proc = QProcess(self)
        proc.setProgram("git")
        proc.setArguments(["-C", str(self.state.data_dir), "pull", "--ff-only"])
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.finished.connect(self._pull_finished)
        proc.errorOccurred.connect(self._pull_error)
        self._pull = proc
        self.status_strip.set_pulling(True)
        proc.start()

    def _pull_finished(self, code: int, _status) -> None:
        proc, self._pull = self._pull, None
        output = bytes(proc.readAll()).decode("utf-8", "replace").strip() if proc else ""
        self.status_strip.set_pulling(False)
        if code != 0:
            self.status_strip.set_error("Pull failed · the local archive is unchanged", output)
            return
        self.reload()

    def _pull_error(self, _error) -> None:
        if self._pull is not None and self._pull.state() == QProcess.ProcessState.NotRunning:
            msg = self._pull.errorString()
            self._pull = None
            self.status_strip.set_pulling(False)
            self.status_strip.set_error("Pull failed · git could not be started", msg)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        save_settings(self.settings, self._settings_file)
        super().closeEvent(event)
