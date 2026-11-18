"""The hourly collector run: one Blizzard snapshot of the house becomes one hour file.

Steps: check the house name; fetch both listing endpoints newer than the last stored
snapshot (polling for up to 5 minutes); look up unknown items; pick the selection;
summarise, compare with the previous listings and write `hourly/` and `house/`; save the
listings for the next run; record a new static namespace in `builds/`; prune window/,
so every uploaded artifact is within the 30-day limit even when a nightly run fails.

The CLI holds the run lock, and the workflow commits and uploads; this module does neither.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

import pandas as pd
import pyarrow.parquet as pq

from .blizzard import BlizzardClient, BlizzardError, Fetched
from .config import Config
from .credentials import load_credentials
from .listings import to_frame
from .sales import auction_changes, compare, load_state, save_state, sold_value
from .selection import build_selection, current_selection
from .store import BUILDS, HOURLY, HOUSE, ITEMS, SELECTION, Store
from .summarise import house_totals, summarise
from .window import keep_days, prune_window

log = logging.getLogger(__name__)

EXIT_OK, EXIT_FAILED = 0, 1
POLL_S = 60
POLLS = 5
LOOKUP_LIMIT = 500  # unknown items looked up per run, the rest next hour
STATE_FILE = "listings.parquet"
SOURCE = "blizzard"
_NAMESPACE = re.compile(r"^static-(\d+(?:\.\d+)*)_(\d+)-")


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_namespace(namespace: str) -> tuple[str | None, int | None]:
    """`static-1.60.1_70399-forever-eu` gives ("1.60.1", 70399); anything else (None, None)."""
    m = _NAMESPACE.match(namespace)
    return (m.group(1), int(m.group(2))) if m else (None, None)


def main(
    cfg: Config,
    client: BlizzardClient | None = None,
    now: Callable[[], datetime] = utcnow,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if client is not None:
        return _run(cfg, client, now, sleep)
    cid, secret = load_credentials()
    with BlizzardClient(cfg.blizzard, cid, secret) as own:
        return _run(cfg, own, now, sleep)


# Steps -------------------------------------------------------------------------


def _latest_observed(store: Store) -> datetime | None:
    """The `observed_at` of the newest stored snapshot."""
    newest = None
    for table in (HOUSE, HOURLY):
        files = store.files(table)
        if not files:
            continue
        col = pq.read_table(files[-1], columns=["observed_at"]).column(0)
        if len(col):
            at = col[0].as_py().astimezone(UTC)  # pyarrow gives ZoneInfo("UTC")
            newest = at if newest is None else max(newest, at)
    return newest


def _fetch(client: BlizzardClient, since: datetime | None, sleep) -> Fetched | None:
    for attempt in range(POLLS + 1):
        fetched = client.listings(since)
        if fetched is not None:
            return fetched
        if attempt < POLLS:
            sleep(POLL_S)
    return None


def _details(store: Store) -> pd.DataFrame:
    """The newest ITEMS row per item (found or not)."""
    tbl = store.read(ITEMS)
    if tbl is None:
        return pd.DataFrame(columns=["item_id", "found", "quality", "class"])
    df = tbl.to_pandas().sort_values(["item_id", "fetched_at"], kind="stable")
    return df.drop_duplicates("item_id", keep="last").reset_index(drop=True)


def _look_up_unknown(client, store: Store, item_ids, limit: int | None, now) -> None:
    known = set(_details(store)["item_id"].astype(int))
    unknown = sorted(int(i) for i in set(item_ids) - known)
    if not unknown:
        return
    batch = unknown if limit is None else unknown[:limit]
    from .master import refresh_items  # WP2; imported here so the run loads without it

    refresh_items(client, store, batch, now())
    log.info("item details: %d of %d unknown items looked up", len(batch), len(unknown))


def _hourly_rows(summary: pd.DataFrame, sales: pd.DataFrame, fetched: Fetched) -> pd.DataFrame:
    df = summary.merge(sales, on="item_id", how="outer")
    for col in ("quantity", "auctions"):
        df[col] = df[col].fillna(0).astype("int32")  # sold out since the previous snapshot
    at = fetched.last_modified
    df["hour"] = at.replace(minute=0, second=0, microsecond=0)
    df["observed_at"] = at
    df["source"] = SOURCE
    return df


def _house_row(frame, prev, span_ok: bool, at: datetime) -> pd.DataFrame:
    row = {
        "hour": at.replace(minute=0, second=0, microsecond=0),
        "observed_at": at,
        "source": SOURCE,
    }
    row.update(house_totals(frame))
    if prev is not None and span_ok:
        row["gone_auctions"], row["new_auctions"] = auction_changes(prev, frame)
        row["sold_value_est"] = sold_value(prev, frame)
    return pd.DataFrame([row])


def _record_build(client: BlizzardClient, store: Store, at: datetime) -> None:
    try:
        namespace = client.static_namespace()
    except BlizzardError as exc:
        log.warning("builds: static namespace not read (%s)", exc)
        return
    if not namespace:
        return
    seen = store.read(BUILDS)
    if seen is not None and seen.num_rows:
        df = seen.to_pandas().sort_values("first_seen", kind="stable")
        if df["namespace"].iloc[-1] == namespace:
            return
    version, build = parse_namespace(namespace)
    row = pd.DataFrame(
        [
            {
                "version": version,
                "build": build,
                "namespace": namespace,
                "first_seen": at,
                "source": SOURCE,
            }
        ]
    )
    path = store.path(BUILDS, at)
    if path.exists():
        row = pd.concat([pd.read_parquet(path), row], ignore_index=True)
    store.write_day(BUILDS, at.date(), row)
    log.info("builds: new static namespace %s", namespace)


def _run(cfg: Config, client: BlizzardClient, now, sleep) -> int:
    name = client.house_name()
    if cfg.blizzard.expect_house_name not in name:
        log.error(
            "house %s is named %r, expected %r in it",
            cfg.blizzard.house,
            name,
            cfg.blizzard.expect_house_name,
        )
        return EXIT_FAILED

    store = Store(cfg.data_dir, cfg.window_dir)
    since = _latest_observed(store)
    fetched = _fetch(client, since, sleep)
    if fetched is None:
        log.info("not modified since %s", since.isoformat() if since else "-")
        return EXIT_OK
    at = fetched.last_modified
    frame = to_frame(fetched)
    log.info(
        "snapshot %s: %d listings, %d items", at.isoformat(), len(frame), frame["item_id"].nunique()
    )

    selected = current_selection(store)
    first = selected is None
    _look_up_unknown(client, store, frame["item_id"].unique(), None if first else LOOKUP_LIMIT, now)
    summary = summarise(frame)
    if first:
        sel = build_selection(summary, _details(store), None, cfg.selection, set(), at.date())
        store.write_day(SELECTION, at.date(), sel)
        selected = set(sel["item_id"].astype(int))
        log.info("selection: first one built, %d items", len(selected))

    state_path = cfg.state_dir / STATE_FILE
    state = load_state(state_path, cfg.blizzard.house, now(), cfg.retention.copied_days)
    prev, prev_at = state if state is not None else (None, None)
    sales = compare(prev, frame, prev_at, at)
    span_ok = sales["span_hours"].notna().any() if len(sales) else False
    if prev is not None and not span_ok:
        log.info("previous listings from %s not comparable, no sales estimate", prev_at)

    rows = _hourly_rows(summary, sales, fetched)
    rows = rows[rows["item_id"].isin(selected)]
    wrote = store.write_hour(HOURLY, at, rows)
    store.write_hour(HOUSE, at, _house_row(frame, prev, span_ok, at))
    if wrote is None:
        log.warning("hour %s was already written, kept", at.isoformat())
    else:
        sold = int(rows["gone_units"].fillna(0).sum()) if span_ok else 0
        log.info("hourly: %d items written, %d units gone", len(rows), sold)

    save_state(state_path, frame, at, cfg.blizzard.house)
    _record_build(client, store, at)
    r = cfg.retention
    prune_window(store, now().date(), keep_days(r.copied_days, r.artifact_days))
    return EXIT_OK
