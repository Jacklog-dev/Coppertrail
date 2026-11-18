"""Master data copied from Blizzard: item details and recipes, kept on the window branch.

Item details go to `blizzard/items/<day>.parquet` (the newest row per item wins across files);
recipes to one `blizzard/recipes/<day>.parquet` per refresh, one row per reagent.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

import pandas as pd

from .blizzard import STATIC, BlizzardClient, BlizzardError
from .store import ITEMS, RECIPES, Store

log = logging.getLogger(__name__)


def _detail_row(item_id: int, detail: dict | None, namespace: str, now: datetime) -> dict:
    if detail is None:
        return {"item_id": item_id, "found": False, "fetched_at": now}
    cls = detail.get("item_class") or {}
    sub = detail.get("item_subclass") or {}
    return {
        "item_id": item_id,
        "found": True,
        "name": detail.get("name"),
        "quality": (detail.get("quality") or {}).get("type"),
        "class_id": cls.get("id"),
        "class": cls.get("name"),
        "subclass_id": sub.get("id"),
        "subclass": sub.get("name"),
        "required_level": detail.get("required_level"),
        "sell_price": detail.get("sell_price"),
        "purchase_price": detail.get("purchase_price"),
        "item_level": detail.get("level"),
        "namespace": namespace or None,
        "fetched_at": now,
    }


def _newest(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["item_id", "fetched_at"], kind="stable")
    return df.drop_duplicates("item_id", keep="last").reset_index(drop=True)


def refresh_items(client: BlizzardClient, store: Store, ids: Iterable[int], now: datetime) -> int:
    """Look the ids up and merge the rows (found or not) into today's ITEMS file.
    An id whose lookup fails with a server error is skipped and tried again later."""
    rows = []
    failed = 0
    for item_id in dict.fromkeys(int(i) for i in ids):
        try:
            detail, namespace = client.item(item_id)
        except BlizzardError as exc:
            if exc.status == 401:
                raise
            failed += 1
            continue
        rows.append(_detail_row(item_id, detail, namespace, now))
    if failed:
        log.warning("item details: %d lookup(s) failed, left for the next run", failed)
    if not rows:
        return 0
    new = pd.DataFrame(rows)
    path = store.path(ITEMS, now.date())
    if path.exists():
        old = pd.read_parquet(path)
        new = pd.concat([old, new.reindex(columns=old.columns)], ignore_index=True)
    store.write_day(ITEMS, now.date(), _newest(new))
    log.info("item details: %d looked up, %d found", len(rows), sum(r["found"] for r in rows))
    return len(rows)


def known_items(store: Store) -> pd.DataFrame:
    """The newest row per item across the window's ITEMS files."""
    tbl = store.read(ITEMS)
    if tbl is None:
        return ITEMS.schema.empty_table().to_pandas()
    return _newest(tbl.to_pandas())


def stale_items(
    store: Store, now: datetime, max_age_days: int = 7, retry_unfound_days: int = 1
) -> list[int]:
    """Found items older than `max_age_days`, unfound ones older than `retry_unfound_days`."""
    k = known_items(store)
    if k.empty:
        return []
    age = now - k["fetched_at"]
    found = k["found"].astype(bool)
    stale = (found & (age > timedelta(days=max_age_days))) | (
        ~found & (age > timedelta(days=retry_unfound_days))
    )
    return sorted(int(i) for i in k.loc[stale, "item_id"])


def _recipe_rows(recipe: dict, profession: str, now: datetime) -> list[dict]:
    base = {
        "recipe_id": recipe["id"],
        "name": recipe.get("name"),
        "profession": profession,
        "crafted_item_id": (recipe.get("crafted_item") or {}).get("id"),
        "crafted_qty": (recipe.get("crafted_quantity") or {}).get("value"),
        "fetched_at": now,
    }
    reagents = recipe.get("reagents") or []
    if not reagents:
        return [base]
    return [
        {**base, "reagent_id": r["reagent"]["id"], "reagent_qty": r.get("quantity")}
        for r in reagents
    ]


def refresh_recipes(client: BlizzardClient, store: Store, now: datetime) -> int:
    """Walk professions â†’ skill tiers â†’ categories â†’ recipes and write today's RECIPES file.
    Returns the number of recipes."""
    rows: list[dict] = []
    seen: set[int] = set()
    index = client.json("/data/wow/profession/index", STATIC)
    for prof in index.get("professions", []):
        name = str(prof.get("name", ""))
        if "[DNT]" in name:
            continue
        detail = client.json(f"/data/wow/profession/{prof['id']}", STATIC)
        for tier in detail.get("skill_tiers") or []:
            path = f"/data/wow/profession/{prof['id']}/skill-tier/{tier['id']}"
            for cat in client.json(path, STATIC).get("categories") or []:
                for ref in cat.get("recipes") or []:
                    if ref["id"] in seen:
                        continue
                    seen.add(ref["id"])
                    try:
                        recipe = client.json(f"/data/wow/recipe/{ref['id']}", STATIC)
                    except BlizzardError as exc:
                        if exc.status != 404:
                            raise
                        log.warning("recipe %s: not found, skipped", ref["id"])
                        continue
                    rows.extend(_recipe_rows(recipe, name, now))
    if rows:
        store.write_day(RECIPES, now.date(), pd.DataFrame(rows))
    count = len({r["recipe_id"] for r in rows})
    log.info("recipes: %d recipes, %d rows", count, len(rows))
    return count
