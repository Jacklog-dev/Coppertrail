from datetime import date

import pandas as pd
import pytest

from coppertrail.collector.config import Selection
from coppertrail.collector.selection import build_selection, current_selection, passes
from coppertrail.collector.store import SELECTION, Store

DAY = date(2026, 11, 18)


def d(quality="COMMON", cls="Trade Goods", found=True):
    return {"found": found, "quality": quality, "class": cls}


@pytest.mark.parametrize(
    "detail,median,expected",
    [
        (d(quality="POOR"), 500, None),
        (d(quality="COMMON"), 49, None),
        (d(quality="COMMON"), 50, "rule"),
        (d(quality="COMMON"), None, None),
        (d(quality="UNCOMMON", cls="Recipe"), 9000, None),
        (d(quality="RARE", cls="Armor"), 9000, None),
        (d(quality="EPIC", cls="Weapon"), 9000, "rule"),
        (d(quality="LEGENDARY", cls="Armor"), 9000, "rule"),
        (d(quality="UNCOMMON", cls="Consumable"), 1, "rule"),
        (d(quality="UNCOMMON", cls="Consumable"), None, "rule"),
        (None, 10, "unclassified"),
        (d(found=False, quality=None, cls=None), 10, "unclassified"),
    ],
)
def test_passes(detail, median, expected):
    assert passes(detail, median, Selection()) == expected


def test_unclassified_excluded_when_switched_off():
    assert passes(None, 10, Selection(include_unclassified=False)) is None


def summary_of(medians: dict[int, int]) -> pd.DataFrame:
    return pd.DataFrame(
        {"item_id": list(medians), "median": pd.array(list(medians.values()), dtype="Int64")}
    )


def details_of(rows: dict[int, dict]) -> pd.DataFrame:
    return pd.DataFrame([{"item_id": i, **r} for i, r in rows.items()])


def test_no_cap_below_max():
    summary = summary_of({1: 100, 2: 100, 3: 10, 4: 100})
    details = details_of({1: d(), 2: d(quality="POOR"), 3: d()})  # 3: median too low; 4: unknown
    sel = build_selection(summary, details, None, Selection(), set(), DAY)
    assert list(sel.columns) == ["day", "item_id", "reason", "rank"]
    assert sel.set_index("item_id")["reason"].to_dict() == {1: "rule", 4: "unclassified"}
    assert sel["rank"].isna().all() and (sel["day"] == DAY).all()


def test_cap_ranks_by_traded_and_keeps_members():
    summary = summary_of({1: 100, 2: 100, 3: 100, 4: 100})
    details = details_of({i: d() for i in (1, 2, 3, 4)})
    traded = pd.Series({1: 900, 2: 800, 3: 700, 4: 600})
    cfg = Selection(max_items=2, keep_rank=3)
    sel = build_selection(summary, details, traded, cfg, previous={3, 4}, day=DAY)
    got = sel.set_index("item_id")["rank"].to_dict()
    assert got == {1: 1, 3: 3}  # 3 is a member within keep_rank; 4 (rank 4) drops out


def test_cap_without_members_takes_top():
    summary = summary_of({1: 100, 2: 100, 3: 100})
    details = details_of({i: d() for i in (1, 2, 3)})
    traded = pd.Series({2: 50, 3: 70})  # item 1 has no traded value: last
    sel = build_selection(summary, details, traded, Selection(max_items=2), set(), DAY)
    assert sel.set_index("item_id")["rank"].to_dict() == {2: 2, 3: 1}


def test_current_selection(tmp_path):
    store = Store(tmp_path, tmp_path / "window")
    assert current_selection(store) is None
    for day, ids in ((date(2026, 11, 17), [1, 2]), (DAY, [2, 3])):
        frame = pd.DataFrame({"day": day, "item_id": ids, "reason": "rule"})
        store.write_day(SELECTION, day, frame)
    assert current_selection(store) == {2, 3}


def test_selection_frame_fits_schema(tmp_path):
    summary = summary_of({1: 100})
    sel = build_selection(summary, details_of({1: d()}), None, Selection(), set(), DAY)
    store = Store(tmp_path, tmp_path / "window")
    store.write_day(SELECTION, DAY, sel)
    assert current_selection(store) == {1}
