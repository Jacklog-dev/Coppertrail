"""Payloads for the GUI states (HANDOVER 8b "States"): stale, no match, pull failed, history."""

from datetime import UTC, date, datetime

from coppertrail.ui.bridge import Bridge, history_gap, pull_failure
from coppertrail.ui.pull import FAILED, NO_GIT, PullResult


def NOW():  # noqa: N802
    return datetime(2026, 11, 16, 9, tzinfo=UTC)


def LATER():  # noqa: N802
    return datetime(2026, 11, 19, 9, tzinfo=UTC)


def test_fresh_status_has_no_banner(archive, config_dir):
    st = Bridge(archive, now=NOW).state()["status"]
    assert st["banner"] is None
    assert st["lastPoint"] == int(datetime(2026, 11, 16, 7, tzinfo=UTC).timestamp())
    assert st["ageDays"] == 0


def test_stale_status_banner_and_chart_tail(archive, config_dir):
    st = Bridge(archive, now=LATER).state()["status"]
    assert st["stale"] and st["ageDays"] == 3
    assert st["banner"] == {
        "title": "Data is 3 days old.",
        "detail": "Charts end on 16 Nov, 08:00.",
    }
    assert st["noDataSince"] == "no data since 16 Nov 08:00"
    assert st["now"] == int(LATER().timestamp())


def test_empty_status(tmp_path, config_dir):
    st = Bridge(tmp_path / "none", now=NOW).state()["status"]
    assert st["banner"] is None and st["lastPoint"] is None and st["ageDays"] is None


def test_no_match_is_none_while_items_show(archive, config_dir):
    assert Bridge(archive, now=NOW).state()["noMatch"] is None


def test_no_match_chips_and_hint(archive, config_dir):
    s = Bridge(archive, now=NOW).set_filters(
        {"groups": ["Herbs"], "item_class": "Consumable", "search": "lotus", "min_sales": 5000}
    )
    assert s["items"]["shown"] == 0
    nm = s["noMatch"]
    assert nm["sub"] == "0 of 9 items · remove one to widen the search"
    assert [c["label"] for c in nm["chips"]] == [
        "Group: Herbs",
        "Class: Consumable",
        "Search: “lotus”",
        "Min sales/day ≥ 5,000",
    ]
    assert [c["clear"] for c in nm["chips"]] == [
        {"groups": []},
        {"item_class": ""},
        {"search": ""},
        {"min_sales": 0},
    ]
    # Dropping any single filter leaves three others; none brings items back.
    assert nm["hint"] is None


def test_no_match_hint_names_best_single_filter(archive, config_dir):
    s = Bridge(archive, now=NOW).set_filters(
        {"groups": ["Leather chain", "Herbs"], "min_sales": 50_000}
    )
    nm = s["noMatch"]
    assert [c["label"] for c in nm["chips"]] == [
        "Groups: Leather chain, Herbs",
        "Min sales/day ≥ 50,000",
    ]
    assert nm["hint"] == {
        "prefix": "Closest: without",
        "label": "Min sales/day ≥ 50,000",
        "result": "→ 6 items",
    }


def test_no_match_ignores_date_range(archive, config_dir):
    s = Bridge(archive, now=NOW).set_filters({"range": "7d", "search": "zzz"})
    assert [c["label"] for c in s["noMatch"]["chips"]] == ["Search: “zzz”"]
    assert s["noMatch"]["hint"]["result"] == "→ 9 items"


def test_no_match_absent_without_items(tmp_path, config_dir):
    s = Bridge(tmp_path / "none", now=NOW).set_filters({"search": "zzz"})
    assert s["noMatch"] is None  # "No data yet" wins


def test_pull_failure_from_git_output():
    r = PullResult(
        False,
        FAILED,
        "From x\nfatal: unable to access 'https://example.invalid/': Could not resolve host",
        returncode=1,
    )
    f = pull_failure(r, as_of=datetime(2026, 11, 16, 7, 42, tzinfo=UTC), at=NOW())
    assert f == {
        "title": "Pull failed",
        "cause": (
            "git stopped: unable to access 'https://example.invalid/': Could not resolve host."
        ),
        "reassurance": (
            "Your local archive is unchanged — everything up to 16 Nov, 08:42 is still here."
        ),
        "request": "git pull --ff-only · exit 1 · 10:00:00",
        "log": r.detail,
    }


def test_pull_failure_without_git_or_archive():
    f = pull_failure(PullResult(False, NO_GIT, "No such file"), as_of=None, at=NOW())
    assert f["cause"] == "git could not be started: No such file."
    assert f["reassurance"] == "Nothing in the data folder was changed."
    assert f["request"] == "git pull --ff-only · 10:00:00"


def test_pull_failure_plain_message():
    f = pull_failure(PullResult(False, FAILED, "", returncode=128), as_of=None, at=NOW())
    assert f["cause"] == "git pull did not finish."
    assert f["log"] == "git printed nothing."


def test_pull_latest_reports_failure(archive, config_dir):
    r = Bridge(archive, now=NOW).pull_latest()
    assert r["ok"] is False
    assert r["failure"]["cause"] == "The data folder is not a git clone."


def test_history_gap_weeks():
    g = history_gap("Reset day", needed=42, have=21, ready_on=date(2026, 12, 7))
    assert g == {
        "title": "Needs 3 more weeks of data",
        "why": (
            "“Reset day” needs 42 days of history. The archive covers 21 so far — "
            "too few to separate a pattern from noise."
        ),
        "progress": "21 of 42 days",
        "ready": "ready around 7 Dec 2026",
        "pct": 50.0,
    }


def test_history_gap_custom_unit():
    g = history_gap("Reset day", needed=6, have=3, ready_on=None, unit="reset", missing_days=21)
    assert g["title"] == "Needs 3 more weeks of data"
    assert g["progress"] == "3 of 6 resets"
    assert g["why"].startswith("“Reset day” needs 6 resets of history.")
    assert g["ready"] == ""
