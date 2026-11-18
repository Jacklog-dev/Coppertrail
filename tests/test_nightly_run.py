"""The nightly run. WP1's selection, summarise and sales modules are replaced by small
fakes that follow the plan's interfaces, so these tests pin nightly's own wiring."""

import importlib
import shutil
import subprocess
import sys
import types
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
import pytest
from blizzard_fixtures import item_detail, mock_transport

from coppertrail.collector import nightly
from coppertrail.collector.blizzard import BlizzardClient
from coppertrail.collector.config import Blizzard, load_config
from coppertrail.collector.store import HOURLY, ITEMS, RECIPES, SELECTION, Store

TUESDAY = datetime(2026, 11, 17, 0, 50, tzinfo=UTC)
MONDAY = datetime(2026, 11, 16, 0, 50, tzinfo=UTC)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(repo, *args):
    out = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture
def wp1(monkeypatch):
    """Fakes for WP1's functions, as the plan's Interfaces state them."""
    seen = {"state": None, "build_args": None}

    def load_state(path, house, now, copied_days):
        return seen["state"]

    def summarise(frame):
        g = frame.groupby("item_id")
        return pd.DataFrame(
            {"item_id": g["unit"].median().index, "median": g["unit"].median().values}
        )

    def build_selection(summary, details, traded, sel, previous, day):
        seen["build_args"] = (summary, details, traded, sel, previous, day)
        return pd.DataFrame(
            {"day": day, "item_id": summary["item_id"], "reason": "rule", "rank": pd.NA}
        )

    def current_selection(store):
        return None

    fakes = {
        "coppertrail.collector.sales": {"load_state": load_state},
        "coppertrail.collector.summarise": {"summarise": summarise},
        "coppertrail.collector.selection": {
            "build_selection": build_selection,
            "current_selection": current_selection,
            "passes": lambda detail, median, sel: "rule",
        },
    }
    for name, attrs in fakes.items():
        try:
            mod = importlib.import_module(name)
        except ImportError:
            mod = types.ModuleType(name)
            monkeypatch.setitem(sys.modules, name, mod)
        for attr, fn in attrs.items():
            monkeypatch.setattr(mod, attr, fn, raising=False)
    return seen


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "data"
    w = d / "window"
    w.mkdir(parents=True)
    git(w, "init", "-q", "-b", "window")
    git(w, "config", "user.email", "test@example.invalid")
    git(w, "config", "user.name", "test")
    (w / "old.txt").write_text("yesterday")
    git(w, "add", "-A")
    git(w, "commit", "-q", "-m", "window yesterday")
    return d


def recipe_routes():
    def js(body):
        return lambda req: httpx.Response(200, json=body)

    return {
        "/data/wow/profession/index": js({"professions": [{"id": 197, "name": "Tailoring"}]}),
        "/data/wow/profession/197": js({"skill_tiers": [{"id": 2948}]}),
        "/data/wow/profession/197/skill-tier/2948": js(
            {"categories": [{"recipes": [{"id": 2359}]}]}
        ),
        "/data/wow/recipe/2359": js(
            {"id": 2359, "name": "Bolt", "reagents": [{"reagent": {"id": 2589}, "quantity": 2}]}
        ),
    }


def client(routes, calls):
    return BlizzardClient(
        Blizzard(rate_per_s=1e9),
        "id",
        "secret",
        transport=mock_transport(routes, calls),
        sleep=lambda s: None,
    )


def state_frame():
    return pd.DataFrame(
        {
            "auction_id": [1, 2, 3],
            "item_id": [10, 10, 20],
            "quantity": [1, 3, 5],
            "time_left": ["LONG", "SHORT", "LONG"],
            "unit": [100.0, 200.0, 30.0],
        }
    )


def hourly_row(item_id, at, median, gone, partial):
    return {
        "item_id": item_id,
        "hour": at.replace(minute=0),
        "observed_at": at,
        "median": median,
        "quantity": 1,
        "auctions": 1,
        "gone_units": gone,
        "partial_units": partial,
        "source": "blizzard",
    }


def test_nightly_writes_selection_and_rebuilds(data, wp1):
    cfg = load_config(data)
    s = Store(cfg.data_dir, cfg.window_dir)
    wp1["state"] = (state_frame(), TUESDAY - timedelta(minutes=28))
    old = TUESDAY - timedelta(days=8)
    s.write_day(
        ITEMS,
        old.date(),
        pd.DataFrame([{"item_id": 10, "found": True, "quality": "COMMON", "fetched_at": old}]),
    )
    s.write_day(RECIPES, old.date(), pd.DataFrame([{"recipe_id": 1, "fetched_at": old}]))
    at = TUESDAY - timedelta(hours=2)
    s.write_hour(
        HOURLY, at, pd.DataFrame([hourly_row(10, at, 150, 2, 1), hourly_row(20, at, 30, None, 4)])
    )
    old_at = TUESDAY - timedelta(days=9)  # outside rank_days
    s.write_hour(HOURLY, old_at, pd.DataFrame([hourly_row(20, old_at, 1000, 50, 0)]))

    calls = []
    route = lambda req: httpx.Response(200, json=item_detail(10, quality="RARE"))  # noqa: E731
    with client({"/data/wow/item/10": route, **recipe_routes()}, calls) as c:
        assert nightly.main(cfg, client=c, now=lambda: TUESDAY) == 0

    sel = pd.read_parquet(s.path(SELECTION, TUESDAY.date()))
    assert sel["item_id"].tolist() == [10, 20]
    summary, details, traded, sel_cfg, previous, day = wp1["build_args"]
    assert day == TUESDAY.date() and previous == set() and sel_cfg == cfg.selection
    assert traded.to_dict() == {10: 450.0, 20: 120.0}
    assert details["item_id"].tolist() == [10]
    assert not any("/profession/" in r.url.path for r in calls)  # Tuesday, recipes present

    items = pd.read_parquet(s.path(ITEMS, TUESDAY.date()))
    assert items["quality"].tolist() == ["RARE"]
    assert s.files(ITEMS) == [s.path(ITEMS, TUESDAY.date())]
    assert s.files(RECIPES) == [s.path(RECIPES, old.date())]
    w = cfg.window_dir
    assert git(w, "rev-list", "--count", "HEAD") == "1"
    assert git(w, "log", "-1", "--format=%s") == "window 2026-11-17"
    assert "old.txt" in git(w, "ls-files")  # untracked by us, but still in the checkout


def test_nightly_without_state_skips_selection(data, wp1):
    cfg = load_config(data)
    s = Store(cfg.data_dir, cfg.window_dir)
    calls = []
    with client(recipe_routes(), calls) as c:
        assert nightly.main(cfg, client=c, now=lambda: TUESDAY) == 0
    assert s.files(SELECTION) == []
    assert wp1["build_args"] is None
    assert git(cfg.window_dir, "log", "-1", "--format=%s") == "window 2026-11-17"


@pytest.mark.parametrize(
    "now,have_recipes,expected",
    [(TUESDAY, True, False), (TUESDAY, False, True), (MONDAY, True, True)],
)
def test_recipes_only_on_monday_or_missing(data, wp1, now, have_recipes, expected):
    cfg = load_config(data)
    s = Store(cfg.data_dir, cfg.window_dir)
    if have_recipes:
        day = now - timedelta(days=3)
        s.write_day(RECIPES, day.date(), pd.DataFrame([{"recipe_id": 1, "fetched_at": day}]))
    calls = []
    with client(recipe_routes(), calls) as c:
        assert nightly.main(cfg, client=c, now=lambda: now) == 0
    fetched = any(r.url.path == "/data/wow/profession/index" for r in calls)
    assert fetched == expected
    if expected:
        assert s.files(RECIPES) == [s.path(RECIPES, now.date())]


def test_nightly_error_exits_1(tmp_path, wp1):
    cfg = load_config(tmp_path)  # window/ is not a git checkout
    with client({}, []) as c:
        assert nightly.main(cfg, client=c, now=lambda: TUESDAY) == 1
