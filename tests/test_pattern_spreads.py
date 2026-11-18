from datetime import date

import numpy as np
import pandas as pd
from pattern_fixtures import hourly_frame, items_frame, make_ctx, noise

import coppertrail.patterns.spreads  # noqa: F401 - registers the job
from coppertrail.patterns.base import run
from coppertrail.patterns.spreads import KEY, WORTH, processing_spreads
from coppertrail.query.series import LATEST_COLS, RECIPE_COLS

START = "2026-11-08 23:00"  # 00:00 CET on 9 Nov
N = 5 * 24

KIT, RUGGED = 15564, 8170
CURED, HIDE, SALT = 4231, 783, 4289
SWORD, BAR = 2000, 2001  # a losing recipe
GEM = 3000  # never priced
RING = 3001

ITEMS = [
    (KIT, "Rugged Armor Kit", 60),
    (RUGGED, "Rugged Leather", 50),
    (CURED, "Cured Light Hide", 10),
    (HIDE, "Light Hide", 10),
    (SALT, "Salt", 5),
    (SWORD, "Iron Sword", 25),
    (BAR, "Iron Bar", 25),
    (RING, "Gem Ring", 30),
]


def _recipe(spell, name, prof, result, rname, reagents, qmin=1, qmax=1):
    return [
        {
            "spell_id": spell,
            "recipe_name": name,
            "profession": prof,
            "skill_required": 100,
            "result_id": result,
            "result_name": rname,
            "result_qty_min": qmin,
            "result_qty_max": qmax,
            "reagent_id": rid,
            "reagent_name": rn,
            "reagent_qty": q,
        }
        for rid, rn, q in reagents
    ]


def _recipes():
    rows = [
        *_recipe(
            19058,
            "Rugged Armor Kit",
            "Leatherworking",
            KIT,
            "Rugged Armor Kit",
            [(RUGGED, "Rugged Leather", 5)],
        ),
        *_recipe(
            3816,
            "Cured Light Hide",
            "Leatherworking",
            CURED,
            "Cured Light Hide",
            [(HIDE, "Light Hide", 1), (SALT, "Salt", 1)],
        ),
        *_recipe(5000, "Iron Sword", "Blacksmithing", SWORD, "Iron Sword", [(BAR, "Iron Bar", 4)]),
        *_recipe(5001, "Gem Ring", "Jewelcrafting", RING, "Gem Ring", [(GEM, "Gem", 1)]),
    ]
    return pd.DataFrame(rows, columns=RECIPE_COLS)


def _flat(item_id, price):
    return hourly_frame(item_id, START, {"min": price * noise(N, item_id, 0.002)})


def _latest(prices):
    return pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-11-13 12:00", tz="UTC"),
                "item_id": i,
                "min_buyout": p,
                "sales_per_day": 10.0,
            }
            for i, p in prices.items()
        ],
        columns=LATEST_COLS,
    )


PRICES = {KIT: 1000, RUGGED: 100, CURED: 230, HIDE: 100, SALT: 100, SWORD: 300, BAR: 100, RING: 500}


def _ctx(prices, recipes=None, **kw):
    return make_ctx(
        hourly=pd.concat([_flat(i, p) for i, p in prices.items()], ignore_index=True),
        items=items_frame(ITEMS),
        latest=_latest(prices),
        recipes=_recipes() if recipes is None else recipes,
        **kw,
    )


def test_planted_leather_chain():
    res = processing_spreads(_ctx(PRICES))
    r = res.ranked
    assert list(r.columns[:2]) == ["item_id", "name"]
    top = r.iloc[0]
    assert top["item_id"] == KIT and top["spell_id"] == 19058
    assert top["name"] == "Rugged Armor Kit"
    assert top["chain"] == "Leather chain"
    assert top["ratio"] == "5 x Rugged Leather -> 1 Rugged Armor Kit"
    # 1000 * 0.95 = 950 against 5 * 100 = 500.
    assert top["value_now"] == 950 and top["cost_now"] == 500
    assert top["margin_now"] == 450 and np.isclose(top["margin_pct_now"], 0.9)
    assert np.isclose(top["mean_margin_30d"], 450, rtol=0.02)
    assert top["days_priced"] == 5 and top["days_worth"] == 5 and top["worth_share"] == 1.0
    cured = r[r["spell_id"] == 3816].iloc[0]
    assert cured["ratio"] == "1 x Light Hide + 1 x Salt -> 1 Cured Light Hide"
    assert cured["chain"] == "Leather chain"
    assert np.isclose(cured["margin_pct_now"], 230 * 0.95 / 200 - 1)  # +9 %, not worth it
    sword = r[r["spell_id"] == 5000].iloc[0]
    assert sword["chain"] == "" and sword["margin_now"] < 0
    assert r["margin_pct_now"].is_monotonic_decreasing
    assert 5001 not in set(r["spell_id"])  # the Gem is unpriced
    assert res.items_checked == 4 and res.items_hit == 1
    assert "1 recipes skipped: unpriced reagent or product" in res.note
    assert "10 %" in res.note
    spread = res.charts["spread"]
    assert list(spread.columns) == ["spell_id", "item_id", "day", "value", "cost", "margin"]
    assert len(spread[spread["spell_id"] == 19058]) == 5
    dm = res.charts["daily_margin"]
    assert list(dm.columns) == ["spell_id", "item_id", "day", "margin", "margin_pct", "worth"]
    assert dm[dm["spell_id"] == 19058]["worth"].all()
    assert WORTH == 0.10


def test_selection_picks_recipes_by_reagent_and_prices_outside_items():
    ctx = _ctx(PRICES)
    h, snap = ctx.hourly, ctx.latest
    # With a selection set, Context reads outside items from disk; serve the presets.
    ctx.hourly_of = lambda ids: h[h["item_id"].isin(list(ids))].reset_index(drop=True)
    ctx.latest_of = lambda ids: snap[snap["item_id"].isin(list(ids))].reset_index(drop=True)
    ctx.item_ids = [RUGGED]  # the kit itself is outside the selection
    res = processing_spreads(ctx)
    assert list(res.ranked["spell_id"]) == [19058]
    assert res.items_checked == 1


def test_unknown_product_uses_recipe_name_and_qty_range():
    rec = pd.DataFrame(
        _recipe(77, "Thing", "Tailoring", 9999, "Odd Thing", [(BAR, "Iron Bar", 2.5)], 1, 2),
        columns=RECIPE_COLS,
    )
    res = processing_spreads(_ctx({9999: 400, BAR: 100}, recipes=rec))
    top = res.ranked.iloc[0]
    assert top["name"] == "Odd Thing"
    assert top["ratio"] == "2.5 x Iron Bar -> 1-2 Odd Thing"
    assert np.isclose(top["value_now"], 1.5 * 400 * 0.95)


def test_flat_spreads_have_no_hits():
    flat = {KIT: 500, RUGGED: 100, CURED: 200, HIDE: 100, SALT: 100, SWORD: 400, BAR: 100}
    res = processing_spreads(_ctx(flat))
    assert res.items_hit == 0
    assert (res.ranked["margin_now"] <= 0).all()


def test_empty_recipes_table():
    res = processing_spreads(_ctx(PRICES, recipes=pd.DataFrame(columns=RECIPE_COLS)))
    assert res.ranked.empty and res.items_checked == 0 and res.note
    assert list(res.ranked.columns[:2]) == ["item_id", "name"]
    assert set(res.charts) == {"spread", "daily_margin"}


def test_no_prices_at_all():
    ctx = make_ctx(recipes=_recipes())
    res = processing_spreads(ctx)
    assert res.ranked.empty and res.items_checked == 4
    assert "4 recipes skipped" in res.note


def test_gate():
    ctx = make_ctx(start=date(2026, 11, 9), end=date(2026, 11, 8))
    ctx.__dict__["span"] = (None, None)
    res = run(KEY, ctx)
    assert res.needs_days == 1 and res.ready_on is not None


def test_chain_by_product_and_history_first():
    # Leather gloves made from Rugged Leather: a reagent in the chain, the product not.
    # The gloves have only a latest price (no hourly history in range), a huge margin.
    gloves = 7777
    rec = pd.concat(
        [
            _recipes(),
            pd.DataFrame(
                _recipe(
                    88, "Gloves", "Leatherworking", gloves, "Rugged Gloves", [(RUGGED, "x", 2)]
                ),
                columns=RECIPE_COLS,
            ),
        ],
        ignore_index=True,
    )
    ctx = _ctx(PRICES, recipes=rec)
    extra = ctx.latest.iloc[[0]].assign(item_id=gloves, min_buyout=1_000_000, sales_per_day=0.0)
    ctx.__dict__["latest"] = pd.concat([ctx.latest, extra], ignore_index=True)
    r = processing_spreads(ctx).ranked
    g = r[r["spell_id"] == 88].iloc[0]
    assert g["chain"] == "" and g["days_priced"] == 0
    assert r.iloc[0]["spell_id"] == 19058  # history first, despite the gloves' margin
    assert r.iloc[-1]["spell_id"] == 88
    assert g["sales_per_day"] == 0.0
