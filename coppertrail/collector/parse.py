"""Turn API answers into flat rows. Prices are copper, times are UTC."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime

SOURCE_API = "api"


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _int_or_none(field: str) -> int | None:
    return int(field) if field != "" else None


@dataclass
class PriceTable:
    market: str
    scanned_at: datetime
    count: int
    rows: list[dict]


def parse_pricetable(text: str) -> PriceTable:
    """Parse the AHL1 price table.

    Header: format|market|unix time|row count. Row columns (documented on
    ahledger.com/developers and checked against /v1/prices on 2026-11-16):
    item id, median, min buyout, quantity, 7-day median, 30-day median,
    30-day low, 30-day high, sales per day x 10. An empty field means unknown.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty price table")
    head = lines[0].split("|")
    if len(head) != 4 or head[0] != "AHL1":
        raise ValueError(f"unexpected price table header: {lines[0]!r}")
    market = head[1].replace("/", ".")
    scanned_at = datetime.fromtimestamp(int(head[2]), tz=UTC)
    rows = []
    for ln in lines[1:]:
        parts = ln.split(":")
        if len(parts) != 9:
            raise ValueError(f"unexpected price table row: {ln!r}")
        v = [_int_or_none(p) for p in parts]
        spd10 = v[8]
        rows.append(
            {
                "item_id": v[0],
                "median": v[1],
                "min_buyout": v[2],
                "quantity": v[3],
                "median_7d": v[4],
                "median_30d": v[5],
                "low_30d": v[6],
                "high_30d": v[7],
                "sales_per_day": spd10 / 10.0 if spd10 is not None else None,
            }
        )
    return PriceTable(market, scanned_at, int(head[3]), rows)


def snapshot_rows(pt: PriceTable, run_id: str) -> list[dict]:
    return [
        {"run_id": run_id, "scanned_at": pt.scanned_at, **r, "source": SOURCE_API} for r in pt.rows
    ]


_POINT_FIELDS = ("min", "p25", "median", "p75", "quantity", "auctions")


def series_rows(
    payload: dict, item_id: int, time_col: str, fetched_at: datetime, run_id: str
) -> list[dict]:
    """Rows from a /v1/prices series. 7d points are hourly buckets (time_col='hour'),
    24h points are one per full scan (time_col='observed_at'); both carry
    {t, min, median, p25, p75, quantity, auctions} (verified 2026-11-16)."""
    rows = []
    for p in payload.get("series") or []:
        rows.append(
            {
                "item_id": item_id,
                time_col: parse_ts(p["t"]),
                **{k: p.get(k) for k in _POINT_FIELDS},
                "source": SOURCE_API,
                "run_id": run_id,
                "fetched_at": fetched_at,
            }
        )
    return rows


def item_rows(tooltip_payload: dict, fetched_at: datetime) -> list[dict]:
    return [
        {
            "item_id": it["id"],
            "name": it.get("name"),
            "quality": it.get("quality"),
            "item_class": it.get("itemClass"),
            "level": it.get("level"),
            "fetched_at": fetched_at,
            "source": SOURCE_API,
        }
        for it in tooltip_payload.get("items") or []
    ]


def economy_rows(payload: dict, fetched_at: datetime, run_id: str) -> list[dict]:
    """One 'daily' row per day of history plus one 'current' row (newest 24 h)."""
    market = payload.get("market")
    rows = []
    for d in payload.get("daily") or []:
        rows.append(
            {
                "market": market,
                "day": datetime.fromisoformat(d["day"]).date(),
                "kind": "daily",
                "observed_at": None,
                "value": d.get("value"),
                "value_low": None,
                "auctions": d.get("auctions"),
                "units": d.get("units"),
                "items": None,
                "scans": d.get("scans"),
                "contributors": None,
                "source": SOURCE_API,
                "run_id": run_id,
                "fetched_at": fetched_at,
            }
        )
    cur = payload.get("current")
    if cur:
        observed = parse_ts(cur["newestScanAt"] if cur.get("newestScanAt") else cur["observedAt"])
        rows.append(
            {
                "market": market,
                "day": observed.date(),
                "kind": "current",
                "observed_at": observed,
                "value": cur.get("value"),
                "value_low": cur.get("valueLow"),
                "auctions": cur.get("auctions"),
                "units": cur.get("units"),
                "items": cur.get("items"),
                "scans": cur.get("scansInWindow"),
                "contributors": cur.get("contributors"),
                "source": SOURCE_API,
                "run_id": run_id,
                "fetched_at": fetched_at,
            }
        )
    return rows


def population_rows(text: str, fetched_at: datetime, run_id: str) -> list[dict]:
    """The CSV layout is not documented; keep every column as text."""
    reader = csv.DictReader(io.StringIO(text))
    return [
        {
            **{k: (v if v is not None else "") for k, v in row.items() if k},
            "fetched_at": fetched_at,
            "run_id": run_id,
            "source": SOURCE_API,
        }
        for row in reader
    ]
