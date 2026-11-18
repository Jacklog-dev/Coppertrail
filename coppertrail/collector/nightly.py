"""The nightly collector run (00:50 UTC).

1. Look up the listed items that have no details yet (at most `MAX_UNKNOWN_PER_NIGHT`), so
   the selection rules see their quality and class instead of treating them as unclassified.
2. Rebuild the item selection from the latest full listings (the hourly run's state).
3. Refresh stale item details (at most `MAX_ITEMS_PER_NIGHT`).
4. Refresh the recipes on Mondays, or when there are none yet.
5. Apply the summary retention, prune window/ (`window.keep_days`).

The workflow uploads window/ as the copied-data artifact and commits main.

The CLI holds the run lock; this module never locks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from .blizzard import BlizzardClient
from .config import Config
from .master import known_items, refresh_items, refresh_recipes, stale_items
from .store import HOURLY, RECIPES, SELECTION, Store
from .window import keep_days, prune_summaries, prune_window

log = logging.getLogger(__name__)

MAX_ITEMS_PER_NIGHT = 3000
MAX_UNKNOWN_PER_NIGHT = 8000  # all listed items fit (about 6,800), well within the timeout
STATE_FILE = "listings.parquet"


def utcnow() -> datetime:
    return datetime.now(UTC)


def state_path(cfg: Config):
    """The previous listings, written by the hourly run (`sales.save_state`)."""
    return cfg.state_dir / STATE_FILE


def traded_gold(store: Store, today: date, rank_days: int) -> pd.Series:
    """Copper per item: sold_est × median summed over the HOURLY rows of the last
    `rank_days` days (today included). sold_est = gone_units + partial_units."""
    tbl = store.read(HOURLY, today - timedelta(days=rank_days - 1), today)
    if tbl is None:
        return pd.Series(dtype="float64")
    df = tbl.select(["item_id", "median", "gone_units", "partial_units"]).to_pandas()
    sold = df["gone_units"].fillna(0).astype("float64") + df["partial_units"].fillna(0)
    value = sold * df["median"].astype("float64").fillna(0)
    return value.groupby(df["item_id"]).sum()


def look_up_unknown(
    client: BlizzardClient, store: Store, frame: pd.DataFrame, now: datetime
) -> int:
    """Look up listed items without a details row (at most `MAX_UNKNOWN_PER_NIGHT`)."""
    known = set(known_items(store)["item_id"].astype(int))
    unknown = sorted(int(i) for i in set(frame["item_id"].astype(int)) - known)
    if not unknown:
        return 0
    batch = unknown[:MAX_UNKNOWN_PER_NIGHT]
    refresh_items(client, store, batch, now)
    log.info("item details: %d of %d unknown items looked up", len(batch), len(unknown))
    return len(batch)


def build_todays_selection(
    cfg: Config, store: Store, now: datetime, frame: pd.DataFrame | None
) -> int | None:
    """Write today's SELECTION from the state listings; None when there is no state."""
    from .selection import build_selection, current_selection
    from .summarise import summarise

    if frame is None:
        log.warning("no listings state yet: selection not rebuilt")
        return None
    today = now.date()
    sel = build_selection(
        summarise(frame),
        known_items(store),
        traded_gold(store, today, cfg.selection.rank_days),
        cfg.selection,
        current_selection(store) or set(),
        today,
    )
    store.write_day(SELECTION, today, sel)
    log.info("selection: %d items", len(sel))
    return len(sel)


def main(
    cfg: Config,
    client: BlizzardClient | None = None,
    now: Callable[[], datetime] = utcnow,
) -> int:
    t = now()
    today = t.date()
    store = Store(cfg.data_dir, cfg.window_dir)
    own_client = client is None
    try:
        from .sales import load_state

        state = load_state(state_path(cfg), cfg.blizzard.house, t, cfg.retention.copied_days)
        frame = state[0] if state is not None else None
        if client is None:
            from .credentials import load_credentials

            client = BlizzardClient(cfg.blizzard, *load_credentials())
        if frame is not None:
            look_up_unknown(client, store, frame, t)
        build_todays_selection(cfg, store, t, frame)
        stale = stale_items(store, t)
        if len(stale) > MAX_ITEMS_PER_NIGHT:
            log.info("item details: %d stale, %d tonight", len(stale), MAX_ITEMS_PER_NIGHT)
        refresh_items(client, store, stale[:MAX_ITEMS_PER_NIGHT], t)
        if t.weekday() == 0 or not store.files(RECIPES):
            refresh_recipes(client, store, t)
        prune_summaries(store, today, cfg.retention.summary_retention_days)
        r = cfg.retention
        prune_window(store, today, keep_days(r.copied_days, r.artifact_days))
    except Exception:
        log.exception("nightly run failed")
        return 1
    finally:
        if own_client and client is not None:
            client.close()
    log.info("nightly run done (%d requests)", client.requests)
    return 0
