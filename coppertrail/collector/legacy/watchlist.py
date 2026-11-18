"""Watchlist selection (HANDOVER section 2): bulk OR valuable, plus pinned and sticky items."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config

COPPER_PER_GOLD = 10_000


@dataclass
class Entry:
    item_id: int
    reason: str  # bulk | valuable | pinned | sticky
    turnover: float  # sales per day x min buyout, copper per day
    scans: bool = False


def turnover(row: dict) -> float:
    spd = row.get("sales_per_day") or 0.0
    return spd * (row.get("min_buyout") or 0)


def rule_reason(row: dict, cfg: Config) -> str | None:
    """'bulk' or 'valuable' if the price-table row passes a rule, else None."""
    spd = row.get("sales_per_day") or 0.0
    qty = row.get("quantity") or 0
    median = row.get("median") or 0
    if spd >= cfg.bulk_min_sales_per_day and qty >= cfg.bulk_min_quantity:
        return "bulk"
    gold_per_day = spd * median / COPPER_PER_GOLD
    if gold_per_day >= cfg.valuable_min_gold_per_day and spd >= cfg.valuable_min_sales_per_day:
        return "valuable"
    return None


def rule_candidates(rows: list[dict], cfg: Config) -> list[int]:
    return [r["item_id"] for r in rows if rule_reason(r, cfg)]


def build_watchlist(
    rows: list[dict],
    cfg: Config,
    qualities: dict[int, str],
    sticky_ids: set[int],
) -> list[Entry]:
    """Rank the watchlist by turnover (highest first, so an interrupted run has the most
    important items) and flag the top `scans_top_n` for per-scan data.

    `qualities` maps item id to quality; items of an excluded quality are dropped unless
    pinned. `sticky_ids` are items that passed a rule in the last `sticky_days` days.
    """
    by_id = {r["item_id"]: r for r in rows}
    excluded = set(cfg.exclude_qualities)
    chosen: dict[int, Entry] = {}

    for r in rows:
        reason = rule_reason(r, cfg)
        if reason and qualities.get(r["item_id"]) not in excluded:
            chosen[r["item_id"]] = Entry(r["item_id"], reason, turnover(r))
    for iid in sticky_ids:
        if iid not in chosen and qualities.get(iid) not in excluded:
            chosen[iid] = Entry(iid, "sticky", turnover(by_id.get(iid, {})))
    for iid in cfg.pinned:
        if iid not in chosen:
            chosen[iid] = Entry(iid, "pinned", turnover(by_id.get(iid, {})))

    ranked = sorted(chosen.values(), key=lambda e: (-e.turnover, e.item_id))
    if cfg.max_items:
        ranked = ranked[: cfg.max_items]
    if cfg.fetch_scans:
        for e in ranked[: cfg.scans_top_n]:
            e.scans = True
    return ranked
