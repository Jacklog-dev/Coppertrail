"""Sales estimate from two snapshots, matched by auction id, and the previous-listings state.

Per item, between the previous snapshot P and the current one C:
- `gone_units`: quantity of P's listings missing in C that were not SHORT in P
  (bought or cancelled, so an upper bound);
- `short_gone_units`: the same for SHORT listings (expired or bought);
- `partial_units`: the positive quantity drop of listings in both;
- `new_units`: quantity of listings new in C;
- `span_hours`: hours between P and C.
All five are NULL when there is no P or the span is outside (0, MAX_SPAN_HOURS].
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

MAX_SPAN_HOURS = 6
SALES_COLUMNS = ["gone_units", "partial_units", "short_gone_units", "new_units", "span_hours"]
STATE_COLUMNS = ["auction_id", "item_id", "quantity", "time_left", "unit"]
_STATE_SCHEMA = pa.schema(
    [
        ("auction_id", pa.int64()),
        ("item_id", pa.int32()),
        ("quantity", pa.int32()),
        ("time_left", pa.string()),
        ("unit", pa.float64()),
    ]
)


def span_hours(prev_at: datetime | None, cur_at: datetime) -> float | None:
    """Hours between the snapshots, or None when they can't be compared."""
    if prev_at is None:
        return None
    span = (cur_at - prev_at).total_seconds() / 3600
    return span if 0 < span <= MAX_SPAN_HOURS else None


def _split(prev: pd.DataFrame, cur: pd.DataFrame):
    """(gone listings of P, listings in both with P's and C's quantity, new listings of C)."""
    both = prev.merge(cur[["auction_id", "quantity"]], on="auction_id", suffixes=("", "_cur"))
    gone = prev[~prev["auction_id"].isin(cur["auction_id"])]
    new = cur[~cur["auction_id"].isin(prev["auction_id"])]
    return gone, both, new


def compare(
    prev: pd.DataFrame | None,
    cur: pd.DataFrame,
    prev_at: datetime | None,
    cur_at: datetime,
) -> pd.DataFrame:
    """One row per item in cur ∪ prev with the sales columns (nullable)."""
    ids = pd.Index(cur["item_id"].unique())
    if prev is not None:
        ids = ids.union(pd.Index(prev["item_id"].unique()))
    out = pd.DataFrame({"item_id": np.sort(ids.to_numpy()).astype("int32")})
    span = span_hours(prev_at, cur_at) if prev is not None else None
    if span is None:
        for col in SALES_COLUMNS[:-1]:
            out[col] = pd.array([pd.NA] * len(out), dtype="Int32")
        out["span_hours"] = pd.array([pd.NA] * len(out), dtype="Float32")
        return out

    gone, both, new = _split(prev, cur)
    short = gone["time_left"] == "SHORT"
    drop = (both["quantity"] - both["quantity_cur"]).clip(lower=0)
    parts = {
        "gone_units": gone[~short].groupby("item_id")["quantity"].sum(),
        "partial_units": drop.groupby(both["item_id"]).sum(),
        "short_gone_units": gone[short].groupby("item_id")["quantity"].sum(),
        "new_units": new.groupby("item_id")["quantity"].sum(),
    }
    for col, series in parts.items():
        values = out["item_id"].map(series).fillna(0).astype("int64")
        out[col] = pd.array(values, dtype="Int32")
    out["span_hours"] = pd.array([span] * len(out), dtype="Float32")
    return out


def sold_value(prev: pd.DataFrame, cur: pd.DataFrame) -> int:
    """Copper: unit × (gone non-SHORT quantity + partial drop); NaN units count as 0."""
    gone, both, _ = _split(prev, cur)
    gone = gone[gone["time_left"] != "SHORT"]
    drop = (both["quantity"] - both["quantity_cur"]).clip(lower=0)
    value = (gone["unit"].fillna(0) * gone["quantity"]).sum()
    value += (both["unit"].fillna(0) * drop).sum()
    return int(np.rint(value))


def auction_changes(prev: pd.DataFrame, cur: pd.DataFrame) -> tuple[int, int]:
    """(listings gone, listings new) between the snapshots, SHORT ones included."""
    gone, _, new = _split(prev, cur)
    return len(gone), len(new)


# State file -------------------------------------------------------------------


def save_state(path: Path, frame: pd.DataFrame, observed_at: datetime, house: int) -> None:
    """The current listings for the next run's compare(), with their time and house."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = frame[STATE_COLUMNS]
    tbl = pa.Table.from_pandas(df, schema=_STATE_SCHEMA, preserve_index=False)
    tbl = tbl.replace_schema_metadata(
        {"observed_at": observed_at.isoformat(), "house": str(int(house))}
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(tbl, tmp, compression="zstd")
    tmp.replace(path)


def load_state(
    path: Path, house: int, now: datetime, copied_days: int
) -> tuple[pd.DataFrame, datetime] | None:
    """The previous listings and their time, or None. A state from another house, older
    than `copied_days` or unreadable is deleted and ignored."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        tbl = pq.read_table(path)
        meta = tbl.schema.metadata or {}
        observed_at = datetime.fromisoformat(meta[b"observed_at"].decode())
        state_house = int(meta[b"house"])
    except Exception as exc:  # noqa: BLE001 - any damage means: start without a state
        log.warning("listings state unreadable (%s), deleted", type(exc).__name__)
        path.unlink(missing_ok=True)
        return None
    if state_house != house:
        log.warning("listings state is from house %s, not %s, deleted", state_house, house)
        path.unlink(missing_ok=True)
        return None
    if now - observed_at > timedelta(days=copied_days):
        log.info("listings state older than %d days, deleted", copied_days)
        path.unlink(missing_ok=True)
        return None
    frame = tbl.replace_schema_metadata(None).to_pandas()
    return frame[STATE_COLUMNS], observed_at
