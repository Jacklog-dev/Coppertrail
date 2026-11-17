# Collector: subclass, vendor price, recipes, builds (2026-11-17)

Feeds patterns 7 (processing spreads), 10 (vendor floor) and 11 (patch effects).
Collector-only change (`coppertrail/collector/`, its tests).

## Verified sources (live, 2026-11-17)

| Need | Source | Fields used |
|---|---|---|
| subclass, vendor price | `GET api.ahledger.com/v1/items/{id}?game=forever` (one item per request; a comma list is `invalid request`) | `itemSubclass` ("Leather", "Herb", "Metal & Stone", "Cloth", ...), `vendorSell` (copper), `requiredLevel`, plus `name`, `quality`, `itemClass`, `level` |
| recipes | `GET /v1/crafting/{market}?all=true&limit=3000` (JSON) | `recipes[].recipe.{spellId,name,profession,skillRequired,acquisition}`, `.result.{id,name,qtyMin,qtyMax}`, `.reagents[].{id,name,qty}` |
| builds | `GET https://ahledger.com/feed/builds.xml` (RSS 2.0) | `item.{title,link,guid,pubDate,description}`; title "WoW Forever [stage ]X.Y.Z (build N): ..." |

Not used:
- `ahledger.com/api/catalog?class=trade-goods` returns `{"rows": [[id, name, quality, subclass, level, requiredLevel, icon, inventoryType], ...]}` (629 rows). It has the subclass but no vendor price, sits on the website (bot check risk), and the other class slugs are undocumented. `/v1/items` covers both needs.
- `/v1/crafting?format=csv` has no reagent columns, so JSON is used. Without `all=true` only 500 priced recipes come back; `all=true&limit=3000` gives all 2,227 (about 2 MB, one request). `limit` above 3000 is rejected.
- `/v1/tooltip` has neither subclass nor vendor price.

## Tables

- `items` gains `subclass` (text), `required_level` (int), `vendor_price` (int, copper). Rows from `/v1/items` are full item rows and, being newer, win over the tooltip row on `item_id`. Readers that pick the newest row per item see the new columns.
- `recipes` (new day-file table, partition `fetched_at`, key `spell_id, reagent_id`): one row per recipe and reagent. Columns `spell_id, recipe_name, profession, skill_required, acquisition, result_id, result_name, result_qty_min, result_qty_max, reagent_id, reagent_name, reagent_qty, source, run_id, fetched_at`. No prices: those come from our own snapshot and hourly data. One fetch per run; a second run on the same day leaves the day file unchanged.
- `builds` (new, partition `published_at`, key `url`): `build_id, version, stage, title, published_at, url, description, source, run_id, fetched_at`. `build_id`/`version`/`stage` are parsed from the title and null when it does not match.

## Run flow

watchlist -> economy -> population -> recipes -> builds -> hourly -> scans -> item details.

- Recipes and builds are one request each and soft errors (noted in the run, run status unchanged). Builds use no retries (website host, like the population CSV).
- Item details: watchlist items (rank order) that have no details row yet (`subclass`, `vendor_price` and `required_level` all null), at most `item_details_per_run` (default 200) per run and inside the `max_run_minutes` budget. About 990 watchlist items exist, so the backfill takes 5 runs at about 7 extra minutes each; afterwards only new watchlist items cost a request. Staged per item, so a resumed run skips done items. A 404 stages nothing and is retried next run.
