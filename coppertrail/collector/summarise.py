"""Per-item summary of one snapshot: quantity-weighted price quantiles and counts."""

from __future__ import annotations

import numpy as np
import pandas as pd

SUMMARY_COLUMNS = ["item_id", "min", "p25", "median", "p75", "quantity", "auctions"]
_QUANTILES = {"p25": 0.25, "median": 0.5, "p75": 0.75}


def weighted_quantile(prices: np.ndarray, weights: np.ndarray, q: float) -> float:
    """The first price, in ascending order, whose cumulative weight is >= q × total."""
    order = np.argsort(prices, kind="stable")
    p, w = np.asarray(prices)[order], np.asarray(weights)[order]
    cum = np.cumsum(w)
    i = int(np.searchsorted(cum, q * cum[-1], side="left"))
    return float(p[min(i, len(p) - 1)])


def _prices(g: pd.DataFrame) -> dict:
    priced = g[g["unit"].notna() & (g["quantity"] > 0)]
    if priced.empty:
        return dict.fromkeys(["min", *_QUANTILES], None)
    units, qty = priced["unit"].to_numpy(), priced["quantity"].to_numpy()
    out = {"min": int(np.rint(units.min()))}
    for col, q in _QUANTILES.items():
        out[col] = int(np.rint(weighted_quantile(units, qty, q)))
    return out


def summarise(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per item; prices are NULL when an item has only bid-only listings."""
    rows = []
    for item_id, g in frame.groupby("item_id", sort=True):
        rows.append(
            {
                "item_id": item_id,
                **_prices(g),
                "quantity": int(g["quantity"].sum()),
                "auctions": len(g),
            }
        )
    df = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    return df.astype(
        {
            "item_id": "int32",
            "min": "Int64",
            "p25": "Int64",
            "median": "Int64",
            "p75": "Int64",
            "quantity": "int32",
            "auctions": "int32",
        }
    )


def house_totals(frame: pd.DataFrame) -> dict:
    """Whole-house counts; `gold_listed` is copper (unit × quantity, bid-only listings left out)."""
    value = (frame["unit"] * frame["quantity"]).sum(skipna=True)
    return {
        "auctions": len(frame),
        "units": int(frame["quantity"].sum()),
        "gold_listed": int(np.rint(value)) if len(frame) else 0,
    }
