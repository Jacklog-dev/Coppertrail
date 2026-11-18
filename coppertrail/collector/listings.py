"""One snapshot's listings (items and commodities) as a flat frame.

`unit` is copper per unit: `unit_price` for commodities, `buyout / quantity` for items,
NaN for bid-only listings (they count in quantity, never in prices).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .blizzard import Fetched

COLUMNS = ["auction_id", "item_id", "quantity", "unit", "time_left", "kind"]


def _rows(auctions: list[dict], kind: str):
    for a in auctions:
        qty = int(a.get("quantity", 0))
        if kind == "commodity":
            price = a.get("unit_price")
            unit = float(price) if price is not None else np.nan
        else:
            buyout = a.get("buyout")
            unit = buyout / qty if buyout is not None and qty > 0 else np.nan
        yield a["id"], a["item"]["id"], qty, unit, str(a.get("time_left", "")), kind


def to_frame(f: Fetched) -> pd.DataFrame:
    rows = [
        *_rows(f.items.get("auctions", []), "item"),
        *_rows(f.commodities.get("auctions", []), "commodity"),
    ]
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df.astype(
        {
            "auction_id": "int64",
            "item_id": "int32",
            "quantity": "int32",
            "unit": "float64",
            "time_left": "object",
            "kind": "object",
        }
    )
