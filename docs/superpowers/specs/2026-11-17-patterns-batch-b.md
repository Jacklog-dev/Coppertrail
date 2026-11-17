# Patterns batch B: patterns 2, 6, 7, 9, 10, 11

Follows `2026-11-17-patterns-batch-a.md` (shared rules unchanged: one module per job, `ranked` starts `item_id, name`, signed fractions, CET = Europe/Berlin, 5 % cut, every job sets `items_checked`, `items_hit` and a `note` with its thresholds). Owns `coppertrail/patterns/` and its tests only.

## New plumbing (all inside `patterns/`)

- `patterns/tables.py`: readers for `recipes` (newest row per spell and reagent), `builds` (newest row per url, `published_at` inside the range) and `item_details` (per item the newest non-null `subclass`, `required_level`, `vendor_price`; tooltip rows carry nulls). Typed empty frames when a table has no day files. **Move to `query/series.py` when the query layer adds them.**
- `Context` gains `details`, `recipes`, `builds`, and `hourly_of(ids)` / `snapshot_of(ids)` for prices of items outside the selection (recipe reagents).
- `common.daily_prices(h)`: per item and CET day the median of hourly min (days with at least 12 hourly rows) plus mean quantity. `inflation.py` now uses it.

## Jobs

| key | no. | data | min days | hit means |
|---|---|---|---|---|
| `processing_spreads` | 7 | recipes, hourly, snapshot, items | 1 | margin now > 0 and worth it on at least half the priced days |
| `vendor_floor` | 10 | hourly, snapshot, items (details) | 1 | at least one hour with min at or below 110 % of the vendor price |
| `build_effects` | 11 | builds, hourly, items | 1 | an item moved 10 % or more beyond the placebo change after a build |
| `weekday_reset` | 2 | hourly, snapshot, items | 28 | weekday amplitude 8 % or more and the peak weekday holds in 75 % of weeks |
| `mean_reversion` | 6 | hourly, snapshot, items | 21 | 3+ signals, hit rate 60 %+ and 10 points above the base rate |
| `correlations` | 9 | hourly, snapshot, items | 21 | the item is in a pair with lagged correlation 0.6 or more on 14+ days |

1. **Processing spreads.** Recipes whose product or a reagent is in the selection. Product quantity = mean of `result_qty_min` and `result_qty_max`. Daily: product value = qty x CET-day price x 0.95, input cost = sum of reagent qty x CET-day price; a day counts only when every reagent and the product are priced. Margin = value - cost, margin_pct = margin / cost; worth it = margin_pct >= 10 %. Now: same from the latest snapshot `min_buyout` (fallback: last priced day). 30 d mean over the last 30 priced days. Recipes with an unpriced item are skipped and counted. `chain` column marks the Leather chain starter group (product or reagent), and the ratio line reads "5 x Rugged Leather -> 1 Rugged Armor Kit". Charts `spread` (per spell and day: value, cost, margin) and `daily_margin` (margin, margin_pct, worth).
2. **Vendor floor.** Vendor price = `vendorSell` (copper a vendor pays), so buying below it and vendoring is risk-free. Per item with vendor price > 0: hours with min <= 110 % of vendor price (near) and < 100 % (below), share of hours, lowest ratio, last time near, current ratio from the snapshot. Items without a vendor price are skipped and counted in the note. Charts `hours` (per item and hour) and `by_hour` (near hours by CET hour).
3. **Build effects.** Builds with at least 12 hourly rows in the 24 h before and after `published_at`. Per item: change of mean min and mean quantity, post vs pre. Placebo = the item's median 24 h-vs-24 h change over all other hours at the same hour of day (day-aligned windows) in the range, which takes out the launch-phase drift. Excess = change - placebo. Per group (starter groups plus "All") the median excess. The note states how many builds were usable. Charts `builds`, `groups`, `window` (per item and build, offset -72..72 h, price and supply index 100 = pre-window mean).
4. **Weekday and reset.** Assumption (unverified for WoW Forever): the EU weekly raid reset is Wednesday 04:00 UTC (05:00 CET), as on EU Classic realms. Daily price and quantity divided by the centred 7-day rolling mean (each weekday once in the window) give a weekday index; per item the mean index per weekday, amplitude = max - min, consistency = share of weeks whose peak-weekday index is above that week's mean. Reset change = median over weeks of the 24 h mean min after the reset against the 24 h before, minus the same for other days at that hour. Charts `weekday` (per item), `market_weekday` (trimmed mean), `reset` (per item and week).
5. **Mean reversion.** Signal day: price at least 15 % below the trailing mean of the previous 7 priced days (at least 5). Recovered: some price within the next 3 days reaches that mean. Base rate: share of all days whose price rises by the same factor (1 / 0.85) within 3 days. Also the 3-day return after the 5 % cut. Charts `signals`, `series`.
6. **Correlations.** Up to 200 items by turnover with daily prices on at least 80 % of the days. Returns = daily log change minus the market's median log change that day, demeaned per item. Lagged correlation for lags -3..3 days (positive lag: partner follows the item), 14 overlapping days at least; best lag per pair by absolute correlation. Pairs ranked by absolute correlation, one row per pair with `item_id` = the leader. The note states the number of pairs tested (many tests: expect some chance pairs). Charts `series` (per item and day: price, residual return) and `lags` (top pairs, per lag).

Gated jobs (2, 6, 9) return `needs_days`/`ready_on` on the real archive (it starts 2026-11-09) and are tested on synthetic data with a planted pattern and a flat-noise negative. Tables the local archive lacks (recipes, builds, item details until the next CI run) are tested on fixtures.

## Changes after review (tested on live recipes and builds in a scratch archive)

- Processing spreads: `chain` goes by the product only (a reagent match tagged every Leatherworking recipe that uses Light Leather). Recipes with priced days rank before snapshot-only ones, because a crafted product without hourly data often has only a fantasy listing. `sales_per_day` is the product's.
- Build effects: windows use the median of hourly min and quantity (single spike hours dominated a mean). A hit also needs `|excess|` of at least 3 robust SDs of the item's placebo changes and beyond every one of them. The note gives how many items that last rule would pick by chance: with about 7 anchors per item and 2 builds that is about half the market, so on 9 days the job cannot tell a build effect from noise.
- Vendor floor: items with a vendor price but no hourly data are checked on their latest snapshot (`hours` = 0).
- Weekday reset: placebo days next to a reset (Tuesday, Thursday) are left out.
- Mean reversion: the base rate asks, for each signal, how often any day rises by the factor that signal needed (mean7 / price).
- Not done: the build placebo only knows builds inside the range, so builds just before the range start are not excluded from anchors.
