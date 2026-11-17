# Market overview and Item detail views

Date: 2026-11-17. Scope: `coppertrail/ui/` and its tests only (the ui session of
`docs/superpowers/plans/2026-11-17-complete-the-app.md`). Visual truth: HANDOVER 8b "Views" and the
mock-ups `MarketOverview`, `ItemDetail`, `Overview1280`, `OverviewUltrawide`.

## Data flow

- `coppertrail/ui/viewdata.py`: pure functions from pandas frames to JSON-able payloads (no locks,
  no I/O besides `query.series` and pattern runs). Tested with small frames and the test archive.
- `bridge.py` adds exposed methods `overview()`, `overview_events()`, `item_list(sort)`,
  `item_detail(item_id)` and `add_to_group(name, item_id)`.
- The four view methods are listed in `Bridge.UNLOCKED`: they copy their inputs (filters, groups,
  items, status, data folder) under the bridge lock, then compute without it, so a slow pattern
  run (supply shocks over ~1,000 items takes ~11 s) never blocks the filter bar. `js_facade` and the
  dev server skip the lock for these names.
- `Memo` (bridge.py): an LRU of futures keyed by (method, inputs, data folder, archive `as_of`).
  Concurrent callers of the same key wait for one computation; a new pull (new `as_of`) or other
  filters give new keys. Pattern runs share one `Context` per (items, range), so hourly is read once.
- Thin query helper in the bridge (not in `query/`): `item_details(data_dir)` reads the newest
  non-null `subclass` and `vendor_price` per item from the items table, tolerating day files that
  predate those columns (the real archive has none yet: vendor price shows "–").

## Shared conventions

- Display strings come from `format.py`: coins as `{parts, text}`, changes as `{text, dir}` with
  ▲/▼ and a real minus, dates `16 Nov 2026`, local times (Europe/Berlin).
- Chart x values are unix seconds (UTC instants); daily points sit at local midnight. Hour-of-day
  charts use x = 0..23 and `xHours: true`.
- Every chart payload carries `sub`, which starts with the date range.
- "7 d" figures (tiles, weekly change in the item list) compare the last full CET day (12+ hours)
  with the full day 7 days earlier (or the archive's first full day), whatever the date filter.
  Charts follow the filter's `date_window`.
- Rows of a payload that are per item always carry `id` and `name`, so the Patterns and Movers
  views can link to Item detail the same way.

## Market overview (`overview`, `overview_events`)

- Tiles: Items tracked (catalog size, "N pass filters"), Median price · 7 d (median weekly change
  over the filtered items; foot: the same per farmable/scarce class from `inflation.classify`),
  Supply · 7 d (summed daily mean quantity of the filtered items), Index divergence (latest
  scarce − farmable from `inflation`). Ultrawide adds Gold listed · 7 d and Auctions · 7 d
  (economy, whole market).
- Price index: `inflation` over the filtered items; scarce `s1` with fill, farmable `s2`, dashed 100,
  tooltip with divergence. A missing basket gives a one-line note in the card.
- Daily rhythm: `daily_rhythm` `market_day` (price = `min_idx`, supply = `quantity_idx`) with min and
  max labelled; with fewer than 7 days the card shows the history gap.
- Total listed supply: hourly sum of quantity over the filtered items (hours where fewer than 80 %
  of the usual item count reported are left out). Total gold listed: economy, whole market (the
  subtitle says so).
- What changed (`overview_events`, slow, loaded after the rest): `mispricings`, `supply_shocks`,
  `buyouts` over the last 7 archive days for the filtered items; 4 rows, strongest per type first.

## Item detail (`item_list`, `item_detail`)

- List: the filtered items, sort by sales/day (default), name, lowest buyout or weekly change; the
  panel's own search filters the loaded rows in JS. Class line = "subclass · class".
- Detail: header (subclass, class, groups, days of history), 5 tiles (lowest buyout vs 7 d ago,
  7-day median with lower quartile, sales/day, listed quantity vs window mean, vendor price),
  price and supply chart (1 h buckets up to 7 days, 6 h beyond; p25 band, vendor floor, markers from
  the three event jobs, shock buckets in `s3`), hour-of-day profile (100 = daily mean), events table.
- "Add to group" opens a menu of groups; "Show in patterns" switches to the Patterns view and
  remembers the item for it.

## Front end

- `web/js/overview.js`, `web/js/itemdetail.js`; `views.js` dispatches and keeps the placeholders for
  Patterns and Movers. Each view shows the loading state, then renders when its payload arrives; a
  newer render drops older answers (request token). Views keep their DOM when only the frame
  re-renders (pull indicator) and the inputs did not change.
- `charts.js` gains: `xHours` (0..23 axis), `tipDate: "day"`, `tipExtra` rows, `labels` (point
  annotations) and `yFromZero: false` for bars.
