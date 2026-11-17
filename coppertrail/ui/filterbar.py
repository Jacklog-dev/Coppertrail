"""The filter bar (HANDOVER 8b "Filter bar"): always visible above every view."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from PySide6.QtCore import QDate, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QCheckBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSpinBox,
    QWidget,
)

from coppertrail.query.catalog import ArchiveStatus, Item
from coppertrail.query.filtering import apply_filters, date_window
from coppertrail.query.groups import ItemGroup
from coppertrail.query.settings import DEFAULT_RANGE, MIN_SALES_PRESETS, Filters
from coppertrail.ui import format as fmt
from coppertrail.ui import theme, tokens
from coppertrail.ui.controls import FieldButton, Popover, Segmented, hline
from coppertrail.ui.widgets import Dot, label

RANGE_OPTIONS = [("24h", "24 h"), ("7d", "7 d"), ("30d", "30 d"), ("all", "All")]


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def _plural(n: int, word: str) -> str:
    return f"{fmt.thousands(n)} {word}{'' if n == 1 else 's'}"


def groups_summary(selected: Sequence[str]) -> str:
    return ", ".join(selected) if selected else "All groups"


class GroupsPopover(Popover):
    """Search, "2 of 6 selected · 84 items", All/None, checkable rows, New/Edit footer."""

    def __init__(self, bar: FilterBar) -> None:
        super().__init__(bar, width=320)
        self.bar = bar
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter groups")
        self.search.addAction(
            theme.icon("search", "text3"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.textChanged.connect(self._apply_search)
        self.body.addWidget(self.search)
        head = QHBoxLayout()
        self.summary = label("", "label", "sub")
        head.addWidget(self.summary)
        head.addStretch(1)
        for text, fn in (("All", self._all), ("None", self._none)):
            b = QPushButton(text)
            b.setProperty("role", "ghost")
            b.clicked.connect(fn)
            head.addWidget(b)
        self.body.addLayout(head)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.body.addWidget(self.list)
        self.body.addWidget(hline())
        foot = QHBoxLayout()
        new = QPushButton("New group")
        new.setIcon(theme.icon("plus"))
        new.setProperty("role", "ghost")
        new.clicked.connect(lambda: self._edit(new_group=True))
        edit = QPushButton("Edit groups…")
        edit.setIcon(theme.icon("edit"))
        edit.setProperty("role", "ghost")
        edit.clicked.connect(lambda: self._edit(new_group=False))
        foot.addWidget(new)
        foot.addStretch(1)
        foot.addWidget(edit)
        self.body.addLayout(foot)
        self._boxes: dict[str, QCheckBox] = {}

    def refresh(self) -> None:
        self.list.clear()
        self._boxes.clear()
        selected = set(self.bar.filters.groups)
        for g in self.bar.groups:
            item = QListWidgetItem()
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(4, 0, 4, 0)
            box = QCheckBox(g.name)
            box.setChecked(g.name in selected)
            box.toggled.connect(self._toggled)
            lay.addWidget(box)
            lay.addStretch(1)
            lay.addWidget(label(_plural(len(g.members(self.bar.items)), "item"), "label", "sub"))
            item.setSizeHint(QSize(0, tokens.SIZES["row_h"] - 4))
            item.setData(Qt.ItemDataRole.UserRole, g.name)
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self._boxes[g.name] = box
        rows = max(1, min(len(self.bar.groups), 8))
        self.list.setFixedHeight(rows * (tokens.SIZES["row_h"] - 4) + 4)
        self._apply_search(self.search.text())
        self._update_summary()

    def _apply_search(self, text: str) -> None:
        needle = text.strip().casefold()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(
                bool(needle) and needle not in item.data(Qt.ItemDataRole.UserRole).casefold()
            )

    def _selected(self) -> list[str]:
        return [g.name for g in self.bar.groups if self._boxes[g.name].isChecked()]

    def _update_summary(self) -> None:
        sel = self._selected()
        chosen = [g for g in self.bar.groups if g.name in sel]
        n_items = len({i.item_id for g in chosen for i in g.members(self.bar.items)})
        self.summary.setText(
            f"{len(sel)} of {len(self.bar.groups)} selected · {_plural(n_items, 'item')}"
        )

    def _toggled(self) -> None:
        self._update_summary()
        self.bar.update_filters(groups=self._selected())

    def _set_all(self, on: bool) -> None:
        for box in self._boxes.values():
            box.blockSignals(True)
            box.setChecked(on)
            box.blockSignals(False)
        self._toggled()

    def _all(self) -> None:
        self._set_all(True)

    def _none(self) -> None:
        self._set_all(False)

    def _edit(self, new_group: bool) -> None:
        self.hide()
        self.bar.edit_groups_requested.emit(new_group)


class DatePopover(Popover):
    """Quick choices, From/To date edits and a calendar; days outside the archive disabled."""

    def __init__(self, bar: FilterBar) -> None:
        super().__init__(bar, width=300)
        self.bar = bar
        self.presets = Segmented(RANGE_OPTIONS)
        self.presets.changed.connect(lambda k: self.bar.update_filters(range=k))
        self.body.addWidget(self.presets)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.addWidget(label("From", "label", "sub"), 0, 0)
        grid.addWidget(label("To", "label", "sub"), 0, 1)
        self.from_edit = QDateEdit()
        self.to_edit = QDateEdit()
        for col, e in enumerate((self.from_edit, self.to_edit)):
            e.setDisplayFormat("dd.MM.yyyy")
            e.dateChanged.connect(self._edited)
            grid.addWidget(e, 1, col)
        self.body.addLayout(grid)
        self.calendar = QCalendarWidget()
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.calendar.setGridVisible(False)
        plain = QTextCharFormat()
        plain.setForeground(theme.color("text1"))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.calendar.setWeekdayTextFormat(day, plain)
        head = QTextCharFormat()
        head.setForeground(theme.color("text3"))
        head.setBackground(theme.color("overlay"))
        self.calendar.setHeaderTextFormat(head)
        self.calendar.clicked.connect(self._clicked)
        self.body.addWidget(self.calendar)
        self.note = label("", "small", "small")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)
        self._pending: date | None = None  # first click of a range pick
        self._painted: list[QDate] = []

    def refresh(self) -> None:
        st: ArchiveStatus = self.bar.status
        lo, hi = date_window(self.bar.filters, st)
        for e in (self.from_edit, self.to_edit, self.calendar):
            e.blockSignals(True)
        if st.first_day and st.last_day:
            for w in (self.from_edit, self.to_edit, self.calendar):
                w.setMinimumDate(_qdate(st.first_day))
                w.setMaximumDate(_qdate(st.last_day))
            self.note.setText(
                f"Archive covers {fmt.date_range(st.first_day, st.last_day)} · "
                "days outside are disabled"
            )
        else:
            self.note.setText("No data yet: the archive is empty")
        self.from_edit.setDate(_qdate(lo))
        self.to_edit.setDate(_qdate(hi))
        self.calendar.setSelectedDate(_qdate(hi))
        for e in (self.from_edit, self.to_edit, self.calendar):
            e.blockSignals(False)
        self.presets.set_value("" if self.bar.filters.range == "custom" else self.bar.filters.range)
        self._paint_range(lo, hi)

    def _paint_range(self, lo: date, hi: date) -> None:
        for q in self._painted:
            self.calendar.setDateTextFormat(q, QTextCharFormat())
        self._painted = []
        fmt_in = QTextCharFormat()
        fmt_in.setBackground(theme.color("accentMuted"))
        fmt_in.setForeground(theme.color("text1"))
        q, end = _qdate(lo), _qdate(hi)
        while q <= end:
            self.calendar.setDateTextFormat(q, fmt_in)
            self._painted.append(q)
            q = q.addDays(1)

    def _edited(self) -> None:
        self._set_custom(_pydate(self.from_edit.date()), _pydate(self.to_edit.date()))

    def _clicked(self, q: QDate) -> None:
        d = _pydate(q)
        if self._pending is None:
            self._pending = d
            self._paint_range(d, d)
            return
        lo, hi = sorted((self._pending, d))
        self._pending = None
        self._set_custom(lo, hi)

    def _set_custom(self, lo: date, hi: date) -> None:
        lo, hi = sorted((lo, hi))
        self.bar.update_filters(range="custom", date_from=lo, date_to=hi)


class MinSalesPopover(Popover):
    """QSpinBox (step 10), preset chips and "412 of 1,284 items pass"."""

    def __init__(self, bar: FilterBar) -> None:
        super().__init__(bar, width=260)
        self.bar = bar
        self.body.addWidget(label("Min sales per day", "label", "sub"))
        self.spin = QSpinBox()
        self.spin.setRange(0, 1_000_000)
        self.spin.setSingleStep(10)
        self.spin.setGroupSeparatorShown(True)
        self.spin.valueChanged.connect(lambda v: self.bar.update_filters(min_sales=int(v)))
        self.body.addWidget(self.spin)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._chips: dict[int, QPushButton] = {}
        for v in MIN_SALES_PRESETS:
            b = QPushButton(fmt.thousands(v))
            b.setProperty("role", "chip")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, v=v: self.spin.setValue(v))
            chips.addWidget(b)
            self._chips[v] = b
        chips.addStretch(1)
        self.body.addLayout(chips)
        self.passing = label("", "label", "sub")
        self.body.addWidget(self.passing)

    def refresh(self) -> None:
        f = self.bar.filters
        self.spin.blockSignals(True)
        self.spin.setValue(f.min_sales)
        self.spin.blockSignals(False)
        for v, b in self._chips.items():
            b.setChecked(v == f.min_sales)
        n = len(apply_filters(self.bar.items, self.bar.groups, f))
        self.passing.setText(f"{fmt.thousands(n)} of {_plural(len(self.bar.items), 'item')} pass")


class FilterBar(QWidget):
    """Groups · Class · Search · Date range · Min sales/day · active count and Reset.

    Holds the filter state; emits `changed` with a copy whenever it changes.
    """

    changed = Signal(object)  # Filters
    edit_groups_requested = Signal(bool)  # True = start with a new group

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FilterBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(tokens.SIZES["filterbar_h"])
        self.filters = Filters()
        self.items: list[Item] = []
        self.groups: list[ItemGroup] = []
        self.status = ArchiveStatus(None, None, None)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(tokens.SIZES["view_pad"], 0, tokens.SIZES["view_pad"], 0)
        lay.setSpacing(10)

        self.groups_btn = FieldButton("Groups", "filter")
        self.groups_btn.setMaximumWidth(300)
        self.groups_pop = GroupsPopover(self)
        self.groups_btn.clicked.connect(lambda: self._open(self.groups_pop, self.groups_btn))
        lay.addWidget(self.groups_btn)
        self.edit_btn = QPushButton()
        self.edit_btn.setIcon(theme.icon("edit"))
        self.edit_btn.setFixedSize(tokens.SIZES["control_h"], tokens.SIZES["control_h"])
        self.edit_btn.setToolTip("Edit item groups")
        self.edit_btn.clicked.connect(lambda: self.edit_groups_requested.emit(False))
        lay.addWidget(self.edit_btn)

        self.class_btn = FieldButton("Class")
        self.class_menu = QMenu(self)
        self.class_btn.clicked.connect(self._open_class_menu)
        lay.addWidget(self.class_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search items")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(
            theme.icon("search", "text3"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.setFixedWidth(220)
        self.search.setFixedHeight(tokens.SIZES["control_h"])
        self._search_timer = QTimer(self, singleShot=True, interval=250)
        self._search_timer.timeout.connect(lambda: self.update_filters(search=self.search.text()))
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        lay.addWidget(self.search)

        self.range = Segmented(RANGE_OPTIONS)
        self.range.changed.connect(lambda k: self.update_filters(range=k))
        lay.addWidget(self.range)
        self.date_btn = FieldButton("", "calendar", chevron=False)
        self.date_pop = DatePopover(self)
        self.date_btn.clicked.connect(lambda: self._open(self.date_pop, self.date_btn))
        lay.addWidget(self.date_btn)

        self.sales_btn = FieldButton("Min sales/day", chevron=False)
        self.sales_pop = MinSalesPopover(self)
        self.sales_btn.clicked.connect(lambda: self._open(self.sales_pop, self.sales_btn))
        lay.addWidget(self.sales_btn)

        lay.addStretch(1)
        self.active_dot = Dot("accent")
        lay.addWidget(self.active_dot)
        self.active_label = QLabel()
        lay.addWidget(self.active_label)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setIcon(theme.icon("reset"))
        self.reset_btn.setFixedHeight(tokens.SIZES["control_h"])
        self.reset_btn.clicked.connect(self.reset)
        lay.addWidget(self.reset_btn)
        self._sync()

    # Data in -----------------------------------------------------------------

    def set_data(self, items: list[Item], groups: list[ItemGroup], status: ArchiveStatus) -> None:
        self.items, self.groups, self.status = items, groups, status
        self._rebuild_class_menu()
        self._sync()

    def set_filters(self, filters: Filters, emit: bool = True) -> None:
        self.filters = replace(filters, groups=list(filters.groups))
        if self.search.text() != self.filters.search:
            self.search.blockSignals(True)
            self.search.setText(self.filters.search)
            self.search.blockSignals(False)
        self._sync()
        if emit:
            self.changed.emit(replace(self.filters, groups=list(self.filters.groups)))

    def update_filters(self, **changes) -> None:
        self.set_filters(replace(self.filters, **changes))

    def reset(self) -> None:
        self.set_filters(Filters())

    # Display -----------------------------------------------------------------

    def _rebuild_class_menu(self) -> None:
        from coppertrail.query.filtering import item_classes

        self.class_menu.clear()
        for value, text in [("", "All classes"), *((c, c) for c in item_classes(self.items))]:
            act = self.class_menu.addAction(text)
            act.setCheckable(True)
            act.setData(value)
            act.triggered.connect(lambda _=False, v=value: self.update_filters(item_class=v))

    def _open_class_menu(self) -> None:
        for act in self.class_menu.actions():
            act.setChecked(act.data() == self.filters.item_class)
        self.class_menu.setMinimumWidth(self.class_btn.width())
        self.class_menu.popup(self.class_btn.mapToGlobal(self.class_btn.rect().bottomLeft()))

    def _open(self, pop: Popover, anchor: QWidget) -> None:
        pop.refresh()
        pop.show_below(anchor)

    def _sync(self) -> None:
        f = self.filters
        self.groups_btn.set_value(groups_summary(f.groups))
        self.groups_btn.set_active(bool(f.groups))
        self.class_btn.set_value(f.item_class or "All classes")
        self.class_btn.set_active(bool(f.item_class))
        theme.set_filter_active(self.search, bool(f.search.strip()))
        self.range.set_value("" if f.range == "custom" else f.range)
        lo, hi = date_window(f, self.status)
        self.date_btn.set_value(fmt.date_range(lo, hi))
        self.date_btn.set_active(f.range == "custom")
        for b in self.range._buttons.values():  # a changed preset is a changed filter too
            theme.set_filter_active(b, f.range != DEFAULT_RANGE and b.isChecked())
        self.sales_btn.set_value(fmt.thousands(f.min_sales))
        self.sales_btn.set_active(bool(f.min_sales))
        active = f.active()
        self.active_dot.setVisible(bool(active))
        self.reset_btn.setVisible(bool(active))
        self.active_label.setText(
            f"{len(active)} filter{'' if len(active) == 1 else 's'} active"
            if active
            else "No filters"
        )
        self.active_label.setProperty("role", "accent" if active else "label")
        self.active_label.setToolTip(", ".join(active))
        self.active_label.style().unpolish(self.active_label)
        self.active_label.style().polish(self.active_label)
        # The groups popover is the source of its own changes and updates itself;
        # rebuilding it here would delete the checkbox whose signal is running.
        for pop in (self.date_pop, self.sales_pop):
            if pop.isVisible():
                pop.refresh()
