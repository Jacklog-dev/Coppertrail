"""Item-group editor (HANDOVER 8b): groups · members · add items, in a modal dialog."""

from __future__ import annotations

import copy

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from coppertrail.query.catalog import Item
from coppertrail.query.groups import ItemGroup
from coppertrail.ui import format as fmt
from coppertrail.ui import theme, tokens
from coppertrail.ui.controls import hline
from coppertrail.ui.widgets import CoinDelegate, CoinLabel, label

MAX_RESULTS = 200
COUNT_ROLE = Qt.ItemDataRole.UserRole + 1


class CountDelegate(QStyledItemDelegate):
    """Group rows: the default row plus the member count right-aligned in text3."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        count = index.data(COUNT_ROLE)
        if count is None:
            return
        painter.save()
        painter.setFont(theme.font("sub"))
        painter.setPen(theme.color("text3"))
        painter.drawText(
            QRect(option.rect).adjusted(0, 0, -10, 0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            fmt.thousands(int(count)),
        )
        painter.restore()


def _pane(width: int | None = None) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("role", "pane")
    if width:
        f.setFixedWidth(width)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(tokens.SPACE[1])
    return f, lay


def _unique_name(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


class GroupEditor(QDialog):
    """Edit a copy of the groups; `result_groups()` after `exec()` returns the saved list."""

    def __init__(
        self,
        groups: list[ItemGroup],
        items: list[Item],
        parent: QWidget | None = None,
        new_group: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit item groups")
        self.setModal(True)
        self.resize(1060, 560)
        self.groups = copy.deepcopy(groups)
        self.items = items
        self.by_id = {i.item_id: i for i in items}
        self.by_name = {i.name.casefold(): i for i in items}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(20, 16, 20, 12)
        head.addWidget(label("Edit item groups", "", "h2"))
        outer.addLayout(head)
        outer.addWidget(hline())

        panes = QHBoxLayout()
        panes.setSpacing(0)
        outer.addLayout(panes, 1)

        # Groups ----------------------------------------------------------------
        left, ll = _pane(240)
        ll.addWidget(label("Groups · drag to reorder", "label", "sub"))
        self.group_list = QListWidget()
        self.group_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.group_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.group_list.setItemDelegate(CountDelegate(self.group_list))
        self.group_list.currentRowChanged.connect(self._show_group)
        self.group_list.model().rowsMoved.connect(self._reordered)
        ll.addWidget(self.group_list, 1)
        btns = QHBoxLayout()
        new = QPushButton("New")
        new.setIcon(theme.icon("plus"))
        new.clicked.connect(self._new)
        dup = QPushButton("Duplicate")
        dup.clicked.connect(self._duplicate)
        self.delete_btn = QPushButton()
        self.delete_btn.setIcon(theme.icon("trash"))
        self.delete_btn.setToolTip("Delete group")
        self.delete_btn.setFixedWidth(tokens.SIZES["control_h"])
        self.delete_btn.clicked.connect(self._delete)
        for b in (new, dup, self.delete_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        ll.addLayout(btns)
        panes.addWidget(left)

        # Members ---------------------------------------------------------------
        mid, ml = _pane()
        ml.addWidget(label("Name", "label", "sub"))
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._renamed)
        ml.addWidget(self.name_edit)
        info = QHBoxLayout()
        self.count_label = label("", "label", "sub")
        info.addWidget(self.count_label)
        info.addStretch(1)
        info.addWidget(label("Tip: paste a list of names, one per line", "label", "sub"))
        ml.addLayout(info)
        self.patterns_label = label("", "small", "small")
        self.patterns_label.setWordWrap(True)
        ml.addWidget(self.patterns_label)
        self.members = QTableWidget(0, 4)
        self.members.setProperty("role", "data")
        self.members.setHorizontalHeaderLabels(["Item", "Class", "Lowest buyout", ""])
        self.members.verticalHeader().hide()
        self.members.setShowGrid(False)
        self.members.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.members.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.members.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.members.verticalHeader().setDefaultSectionSize(tokens.SIZES["row_h"])
        self.members.setItemDelegateForColumn(2, CoinDelegate(self.members))
        hh = self.members.horizontalHeader()
        hh.setFont(theme.font("th"))
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.members.setColumnWidth(3, 36)
        self.members.horizontalHeaderItem(2).setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        ml.addWidget(self.members, 1)
        panes.addWidget(mid, 1)

        # Add items -------------------------------------------------------------
        right, rl = _pane(300)
        rl.addWidget(label("Add items", "label", "sub"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search items")
        self.search.addAction(
            theme.icon("search", "text3"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.textChanged.connect(self._search)
        rl.addWidget(self.search)
        self.result_label = label("", "label", "sub")
        rl.addWidget(self.result_label)
        self.results = QListWidget()
        self.results.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rl.addWidget(self.results, 1)
        self.add_btn = QPushButton("Add selected")
        self.add_btn.setIcon(theme.icon("plus"))
        self.add_btn.clicked.connect(self._add_selected)
        rl.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignLeft)
        panes.addWidget(right)

        outer.addWidget(hline())
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 12, 20, 12)
        foot.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("role", "ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save groups")
        save.setProperty("role", "primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(save)
        outer.addLayout(foot)

        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._paste)
        self._result_boxes: list[tuple[QCheckBox, int]] = []
        self._fill_group_list()
        if new_group:
            self._new()
        elif self.groups:
            self.group_list.setCurrentRow(0)
        self._search("")

    # Helpers -----------------------------------------------------------------

    def result_groups(self) -> list[ItemGroup]:
        return self.groups

    def current(self) -> ItemGroup | None:
        row = self.group_list.currentRow()
        return self.groups[row] if 0 <= row < len(self.groups) else None

    def _fill_group_list(self, select: int | None = None) -> None:
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for g in self.groups:
            it = QListWidgetItem(theme.icon("grip", "text3", size=14), g.name)
            it.setSizeHint(QSize(0, tokens.SIZES["row_h"]))
            self.group_list.addItem(it)
        self.group_list.blockSignals(False)
        if select is not None and self.groups:
            self.group_list.setCurrentRow(max(0, min(select, len(self.groups) - 1)))
        self._update_group_counts()

    def _update_group_counts(self) -> None:
        for row, g in enumerate(self.groups):
            it = self.group_list.item(row)
            if it:
                it.setData(COUNT_ROLE, len(g.members(self.items)))
        self.delete_btn.setEnabled(bool(self.groups))

    # Groups pane -------------------------------------------------------------

    def _new(self) -> None:
        name = _unique_name("New group", {g.name for g in self.groups})
        self.groups.append(ItemGroup(name))
        self._fill_group_list(select=len(self.groups) - 1)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _duplicate(self) -> None:
        g = self.current()
        if not g:
            return
        dup = copy.deepcopy(g)
        dup.name = _unique_name(f"{g.name} copy", {x.name for x in self.groups})
        row = self.group_list.currentRow() + 1
        self.groups.insert(row, dup)
        self._fill_group_list(select=row)

    def _delete(self) -> None:
        row = self.group_list.currentRow()
        if 0 <= row < len(self.groups):
            del self.groups[row]
            self._fill_group_list(select=row)
            if not self.groups:
                self._show_group(-1)

    def _reordered(self, *_args) -> None:
        by_name = {g.name: g for g in self.groups}
        order = [self.group_list.item(i).text() for i in range(self.group_list.count())]
        self.groups = [by_name[n] for n in order if n in by_name]

    def _renamed(self, text: str) -> None:
        g = self.current()
        name = text.strip()
        if not g or not name or name in {x.name for x in self.groups if x is not g}:
            return
        g.name = name
        self.group_list.currentItem().setText(name)

    # Members pane ------------------------------------------------------------

    def _show_group(self, row: int) -> None:
        g = self.groups[row] if 0 <= row < len(self.groups) else None
        self.name_edit.setEnabled(g is not None)
        self.name_edit.setText(g.name if g else "")
        self._fill_members()
        self._search(self.search.text())

    def _fill_members(self, note: str = "") -> None:
        g = self.current()
        members = sorted(g.members(self.items), key=lambda i: i.name) if g else []
        self.members.setRowCount(len(members))
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for r, item in enumerate(members):
            self.members.setItem(r, 0, QTableWidgetItem(item.name))
            cls = QTableWidgetItem(item.item_class)
            cls.setForeground(theme.color("text2"))
            self.members.setItem(r, 1, cls)
            price = QTableWidgetItem()
            price.setData(Qt.ItemDataRole.UserRole, item.min_buyout)
            price.setTextAlignment(right)
            self.members.setItem(r, 2, price)
            rm = QPushButton()
            rm.setProperty("role", "ghost")
            rm.setIcon(theme.icon("x", "text3"))
            rm.setToolTip(f"Remove {item.name}")
            rm.clicked.connect(lambda _=False, iid=item.item_id: self._remove(iid))
            self.members.setCellWidget(r, 3, rm)
        count = (
            f"{fmt.thousands(len(members))} item{'' if len(members) == 1 else 's'} in this group"
        )
        self.count_label.setText(count + (f" · {note}" if note else ""))
        pats = ", ".join(g.patterns) if g and g.patterns else ""
        self.patterns_label.setText(f"Also matches names like: {pats}" if pats else "")
        self.patterns_label.setVisible(bool(pats))
        self._update_group_counts()

    def _remove(self, item_id: int) -> None:
        g = self.current()
        if g:
            g.remove(item_id)
            self._fill_members()
            self._search(self.search.text())

    def _paste(self) -> None:
        g = self.current()
        text = QApplication.clipboard().text()
        if not g or not text or self.focusWidget() in (self.name_edit, self.search):
            if self.focusWidget() in (self.name_edit, self.search):
                self.focusWidget().paste()
            return
        names = [ln.strip() for ln in text.splitlines() if ln.strip()]
        found = [self.by_name[n.casefold()] for n in names if n.casefold() in self.by_name]
        for item in found:
            g.add(item.item_id)
        missing = len(names) - len(found)
        self._fill_members(
            f"{missing} pasted name{'' if missing == 1 else 's'} not found" if missing else ""
        )
        self._search(self.search.text())

    # Add-items pane ----------------------------------------------------------

    def _search(self, text: str) -> None:
        self.results.clear()
        self._result_boxes = []
        g = self.current()
        needle = text.strip().casefold()
        if not g or not needle:
            self.result_label.setText("Type to search the catalog")
            self._update_add_button()
            return
        hits = [i for i in self.items if needle in i.name.casefold() and not g.matches(i)]
        self.result_label.setText(
            f"{fmt.thousands(len(hits))} result{'' if len(hits) == 1 else 's'} not yet in group"
        )
        for item in hits[:MAX_RESULTS]:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(4, 0, 4, 0)
            box = QCheckBox(item.name)
            box.toggled.connect(self._update_add_button)
            lay.addWidget(box, 1)
            if item.min_buyout is not None:
                lay.addWidget(CoinLabel(item.min_buyout, align=Qt.AlignmentFlag.AlignRight))
            it = QListWidgetItem()
            it.setSizeHint(QSize(0, tokens.SIZES["row_h"]))
            self.results.addItem(it)
            self.results.setItemWidget(it, row)
            self._result_boxes.append((box, item.item_id))
        self._update_add_button()

    def _update_add_button(self) -> None:
        n = sum(1 for box, _ in self._result_boxes if box.isChecked())
        self.add_btn.setText(f"Add {n} selected" if n else "Add selected")
        self.add_btn.setEnabled(n > 0)

    def _add_selected(self) -> None:
        g = self.current()
        if not g:
            return
        for box, item_id in self._result_boxes:
            if box.isChecked():
                g.add(item_id)
        self._fill_members()
        self._search(self.search.text())
