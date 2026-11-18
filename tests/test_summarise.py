from datetime import UTC, datetime

import numpy as np
import pandas as pd
from blizzard_fixtures import commodity, item_auction

from coppertrail.collector.blizzard import Fetched
from coppertrail.collector.listings import to_frame
from coppertrail.collector.summarise import house_totals, summarise, weighted_quantile

T0 = datetime(2026, 11, 18, 11, 22, 52, tzinfo=UTC)


def fetched(items=(), commodities=()):
    return Fetched(
        items={"auctions": list(items)},
        commodities={"auctions": list(commodities)},
        last_modified=T0,
        namespace="dynamic-forever-eu",
    )


def frame_of(rows):
    """(item_id, quantity, unit) rows as commodity listings with ids 1, 2, ..."""
    return to_frame(
        fetched(commodities=[commodity(i, it, q, u) for i, (it, q, u) in enumerate(rows, 1)])
    )


def test_unit_price_from_buyout_and_commodity():
    f = to_frame(
        fetched(items=[item_auction(1, 10, 4, buyout=400)], commodities=[commodity(2, 20, 5, 30)])
    ).set_index("auction_id")
    assert f.loc[1, "unit"] == 100 and f.loc[2, "unit"] == 30
    assert f.loc[1, "kind"] == "item" and f.loc[2, "kind"] == "commodity"


def test_frame_dtypes():
    f = to_frame(fetched(items=[item_auction(1, 10, 2, bid=50, time_left="SHORT")]))
    assert str(f["auction_id"].dtype) == "int64" and str(f["item_id"].dtype) == "int32"
    assert str(f["quantity"].dtype) == "int32" and str(f["unit"].dtype) == "float64"
    assert f.loc[0, "time_left"] == "SHORT" and np.isnan(f.loc[0, "unit"])


def test_empty_frame_has_columns():
    f = to_frame(fetched())
    assert list(f.columns) == ["auction_id", "item_id", "quantity", "unit", "time_left", "kind"]
    assert summarise(f).empty


def test_weighted_quantile_rule():
    prices, weights = np.array([200.0, 100.0]), np.array([3, 1])
    # first price whose cumulative quantity is >= q * total (here 1, 2, 3 of 4)
    assert weighted_quantile(prices, weights, 0.25) == 100
    assert weighted_quantile(prices, weights, 0.5) == 200
    assert weighted_quantile(prices, weights, 0.0) == 100


def test_weighted_quantiles():
    s = summarise(frame_of([(10, 1, 100), (10, 3, 200)]))  # (item, qty, unit)
    r = s.iloc[0]
    got = (r["min"], r["p25"], r["median"], r["p75"], r["quantity"], r["auctions"])
    assert got == (100, 100, 200, 200, 4, 2)


def test_prices_rounded_to_int():
    s = summarise(to_frame(fetched(items=[item_auction(1, 10, 3, buyout=100)])))
    assert s.iloc[0]["median"] == 33 and str(s["median"].dtype) == "Int64"


def test_bid_only_counts_quantity_not_price():
    s = summarise(
        to_frame(fetched(items=[item_auction(1, 10, 2, bid=50), item_auction(2, 11, 1, buyout=7)]))
    ).set_index("item_id")
    assert s.loc[10, "quantity"] == 2 and s.loc[10, "auctions"] == 1
    assert pd.isna(s.loc[10, "median"]) and pd.isna(s.loc[10, "min"])
    assert s.loc[11, "median"] == 7


def test_bid_only_listing_not_in_prices_of_priced_item():
    f = to_frame(fetched(items=[item_auction(1, 10, 5, bid=1), item_auction(2, 10, 1, buyout=90)]))
    r = summarise(f).iloc[0]
    assert (r["min"], r["median"], r["quantity"], r["auctions"]) == (90, 90, 6, 2)


def test_house_totals():
    assert house_totals(frame_of([(10, 2, 100), (20, 1, 5)])) == {
        "auctions": 2,
        "units": 3,
        "gold_listed": 205,
    }
