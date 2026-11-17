from datetime import date

import pandas as pd
import pytest

from coppertrail.patterns import base
from coppertrail.patterns.base import Context, PatternResult, events_frame, pattern, run


@pytest.fixture
def registry():
    """The real registry, emptied for the test and restored after it."""
    saved = dict(base.REGISTRY)
    base.REGISTRY.clear()
    yield base.REGISTRY
    base.REGISTRY.clear()
    base.REGISTRY.update(saved)


def _register(min_days: int):
    @pattern(
        "count",
        number=99,
        title="Row count",
        min_days=min_days,
        data=("hourly",),
        method="Counts hourly rows.",
    )
    def count(ctx: Context) -> PatternResult:
        h = ctx.hourly
        ranked = h.groupby("item_id", as_index=False).size().rename(columns={"size": "rows"})
        return PatternResult(
            ranked=ranked, items_checked=len(ranked), items_hit=len(ranked), note="(test)"
        )

    return count


def test_run_fills_basis(archive, registry):
    _register(min_days=3)
    ctx = Context(archive, [2318], date(2026, 11, 1), date(2026, 11, 30))
    res = run("count", ctx)
    assert res.ready
    assert (res.first_day, res.last_day, res.days_used) == (
        date(2026, 11, 9),
        date(2026, 11, 16),
        8,
    )
    assert res.ranked["rows"].tolist() == [192]
    assert res.method == "Counts hourly rows. (test)"
    assert res.basis_line().startswith("Rests on 8 days of data (2026-11-09 to 2026-11-16)")


def test_too_little_history_skips_the_job(archive, registry):
    fn = _register(min_days=28)
    called = []
    registry["count"] = base.PatternSpec(
        "count", 99, "Row count", 28, ("hourly",), "m", lambda c: called.append(1) or fn(c)
    )
    res = run("count", Context(archive, None, date(2026, 11, 9), date(2026, 11, 16)))
    assert not res.ready and not called
    assert res.needs_days == 20
    assert res.ready_on == date(2026, 12, 6)
    assert "Needs 20 more days" in res.basis_line()


def test_empty_archive_is_not_ready(tmp_path, registry):
    _register(min_days=1)
    res = run("count", Context(tmp_path, None, date(2026, 11, 9), date(2026, 11, 16)))
    assert res.days_used == 0 and res.needs_days == 1


def test_duplicate_and_bad_registration(registry):
    _register(min_days=1)
    with pytest.raises(ValueError):
        _register(min_days=1)
    with pytest.raises(ValueError):
        pattern("x", number=1, title="x", min_days=1, data=("nope",), method="")


def test_events_frame_schema():
    ev = events_frame(
        [{"item_id": 1, "at": "2026-11-16T07:00Z", "type": "buyout", "detail": "d", "magnitude": 1}]
    )
    assert list(ev.columns) == base.EVENT_COLS
    assert str(ev["at"].dt.tz) == "UTC"
    assert events_frame().empty
    with pytest.raises(ValueError):
        events_frame([{"item_id": 1, "at": pd.Timestamp.now(tz="UTC"), "type": "x"}])


def test_cli_list_and_run(archive, registry, capsys):
    from coppertrail.patterns.__main__ import main

    _register(min_days=1)
    assert main(["--data-dir", str(archive), "list"]) == 0
    assert "count" in capsys.readouterr().out
    assert main(["--data-dir", str(archive), "run", "count"]) == 0
    out = capsys.readouterr().out
    assert "Rests on 8 days" in out and "192" in out
    assert main(["--data-dir", str(archive), "run", "nope"]) == 2
