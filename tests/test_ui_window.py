"""Window frame, filter bar and group editor, headless."""

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from coppertrail.query.groups import load_groups  # noqa: E402
from coppertrail.query.settings import Filters, load_settings  # noqa: E402
from coppertrail.ui import theme  # noqa: E402
from coppertrail.ui.groupeditor import GroupEditor  # noqa: E402
from coppertrail.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    theme.apply_theme(qapp)
    return qapp


@pytest.fixture
def window(app, archive, config_dir):
    win = MainWindow(data_dir=archive)
    yield win
    win.close()


def test_frame_loads_archive(window):
    view = window.views[0]
    assert view.sub.text() == "9 of 9 items"
    assert window.filter_bar.active_label.text() == "No filters"
    assert window.filter_bar.date_btn._value.text() == "9 Nov – 16 Nov 2026"
    assert window.status_strip.text.text().startswith("Data ")
    assert "AHledger" in " ".join(
        b.text() for b in window.status_strip.findChildren(type(window.nav.data_btn))
    )
    assert not window.status_strip.pull.isEnabled()  # fixture folder is not a git clone


def test_filters_apply_mark_and_persist(window, config_dir):
    bar = window.filter_bar
    bar.update_filters(groups=["Leather chain"], min_sales=50)
    assert window.views[0].sub.text() == "2 of 9 items"
    assert bar.active_label.text() == "2 filters active"
    assert bar.groups_btn.property("filterActive") is True
    assert bar.class_btn.property("filterActive") is False
    assert load_settings().filters.groups == ["Leather chain"]  # remembered
    bar.reset()
    assert window.views[0].sub.text() == "9 of 9 items"
    assert bar.groups_btn.property("filterActive") is False
    assert load_settings().filters == Filters()


def test_data_dir_override_is_not_saved(window, config_dir):
    window.filter_bar.update_filters(min_sales=10)
    assert load_settings().data_dir == ""


def test_popovers_show_counts(window, app):
    bar = window.filter_bar
    bar.update_filters(groups=["Leather chain", "Herbs"])
    bar.groups_pop.refresh()
    assert bar.groups_pop.summary.text() == "2 of 6 selected · 6 items"
    bar.update_filters(min_sales=50)
    bar.sales_pop.refresh()
    assert bar.sales_pop.passing.text() == "3 of 9 items pass"  # Light, Rugged Leather, Peacebloom
    bar.date_pop.refresh()
    assert "9 Nov" in bar.date_pop.note.text()
    bar.date_pop._set_custom(date(2026, 11, 12), date(2026, 11, 10))  # order-insensitive
    assert bar.filters.range == "custom"
    assert bar.date_btn._value.text() == "10 Nov – 12 Nov 2026"
    assert bar.range.value() == ""  # no preset highlighted for a custom range


def test_group_editor_edits_a_copy(window, app):
    items = window.state.items
    groups = window.state.groups
    dlg = GroupEditor(groups, items, window)
    assert dlg.group_list.count() == 6
    dlg.group_list.setCurrentRow(0)  # Leather chain
    assert dlg.members.rowCount() == 4
    dlg._remove(2318)
    assert dlg.members.rowCount() == 3
    dlg.search.setText("potion")
    assert len(dlg._result_boxes) == 1
    dlg._result_boxes[0][0].setChecked(True)
    assert dlg.add_btn.text() == "Add 1 selected"
    dlg._add_selected()
    assert dlg.members.rowCount() == 4
    dlg._new()
    assert dlg.current().name == "New group"
    QApplication.clipboard().setText("Peacebloom\nNo Such Item\nblack lotus\n")
    dlg.members.setFocus()
    dlg._paste()
    assert {i.name for i in dlg.current().members(items)} == {"Peacebloom", "Black Lotus"}
    assert "1 pasted name not found" in dlg.count_label.text()
    assert len(groups) == 6  # the caller's list is untouched until saved
    assert len(dlg.result_groups()) == 7


def test_saving_groups_drops_stale_selection(window, monkeypatch, config_dir):
    window.filter_bar.update_filters(groups=["Herbs"])

    def fake_exec(dlg):
        dlg.group_list.setCurrentRow(3)  # Herbs
        dlg._delete()
        return True

    monkeypatch.setattr(GroupEditor, "exec", fake_exec)
    window.edit_groups()
    assert "Herbs" not in [g.name for g in load_groups()]
    assert window.state.filters.groups == []
