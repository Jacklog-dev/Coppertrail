# Patterns and Movers & outliers views

Date: 2026-11-17. Scope: `coppertrail/ui/` and its tests only (Phase 3 of
`docs/superpowers/plans/2026-11-17-complete-the-app.md`). Visual truth: HANDOVER 8b "Views" and the
mock-ups `PatternsRhythm`, `PatternsSpreads`, `Movers`, `States` (too little history). Reuses the
payload style, `Memo` caching and `ViewInputs` of `2026-11-17-market-item-views.md`.

## Data flow

- `coppertrail/ui/patternview.py`: pure builders from a `PatternResult` (plus the item names and,
  where a chart needs raw series, the job's `Context`) to the Patterns payload. One builder per job;
  a generic table and chart schema (below) so the front end does not know the 12 jobs.
- `coppertrail/ui/movers.py`: pure builders for risers/fallers and current mispricings.
- `bridge.py` adds exposed, unlocked, memoized methods `patterns(key, select, item, sort)`,
  `movers(range)` and `mispricings_now(threshold)`. Pattern results are cached per
  (key, `ViewInputs.key`), so clicking rows or sorting does not rerun a job.
- Front end: `web/js/patterns.js` + `web/css/patterns.css`, `web/js/movers.js` + `web/css/movers.css`,
  `views.js` dispatches. Generic chart building on `charts.js`, which gains `xTicks` (categorical or
  numeric x), `vLines` (vertical markers with a label) and a `color` per reference line.

## Patterns payload (`patterns(key=None, select=None, item=None, sort=None)`)

```
{sub, tabs: [{key, title, number, chip: "needs data" | null}], key, title,
 basis: {lead: "Rests on 8 days", text: " of data (9 – 16 Nov 2026) · 987 items checked · …",
         method: short note (right), detail: the job's full method (tooltip)},
 state: "ready" | "history" | "waiting" | "error",
 gap: history_gap()            # state "history" (too little history, with the ready date)
 waiting: {title, text}        # state "waiting": the job's input table is still empty
 error: "Could not compute …"  # state "error"
 charts: [chart, chart],       # state "ready" (a chart may carry `note` instead of data)
 table: {title, sorts: [{key, label}], sort, columns: [{label, kind, num}],
         rows: [{id, item, cells: [...]}], selected, more, note}}
```

- Tabs: every job in `REGISTRY`, ordered by number. Chip "needs data" when the archive is shorter
  than `min_days` (cheap: no run) or the job's input is empty (recipes, builds, vendor prices).
- Default tab: `daily_rhythm`; `item` (Item detail's "Show in patterns") selects the first row of
  that item in the current tab; `select` is a row id (item id; spell id for spreads; "a-b" pairs).
- Table cells by column `kind`: `rank` (text), `item` ({name, sub?}), `text`, `muted`, `num`
  (text), `change` ({text, dir}), `coin` (coin dict, `neg` for losses), `bar` ({share, text,
  color}), `level` ({text, tone: text1/text2/text3}). Up to 200 rows.
- Chart: `{title, sub, legend, x, xKind: time|day|hour|cat|num, xLabels?, xSuffix?, series:
  [{label, color, width?, fill?, bars?, values}], bands?, refLines?: [{value, label?, color?}],
  vLines?: [{x, label, color}], labels?, markers?, y: percent|coins|index|count|plain, height}`.
  Bars with two colours (won/lost, worth/thin/loss) are separate bar series with nulls.
- Waiting texts: recipes (pattern 7), builds (11) and vendor prices (10) are filled by the
  collector from 18 Nov 2026; the tab says what it waits for and that a pull brings it.

Per job (charts left, table right; first chart follows the selected row):

| no. | job | charts | table |
|---|---|---|---|
| 1 | daily_rhythm | nights (won `rise`, lost `fall`, dashed mean `s1`), typical day (min `s1`, supply `s2`, buy/sell lines) | wins/nights bar, avg result, sales/day, confidence |
| 2 | weekday_reset | item weekday index (price `s1`, supply `s2`), market weekday | peak/trough day, amplitude, consistency, reset change |
| 3 | mispricings | item scans (min `s1`, p25 `s2`, mispricing markers), events by hour | events, median depth, deepest, back after, corrected |
| 4 | supply_shocks | item listed quantity (shock hours `s3`), price after a shock by lag (item vs all) | shocks, jump, price after, lag, fell after |
| 5 | buyouts | item scans (min `s1`, quantity hidden, buyout markers), buyouts by hour | buyouts, quantity drop, min jump, reset after |
| 6 | mean_reversion | item price, 7-day mean, threshold, signal markers | signals, hit rate, base rate, edge, return |
| 7 | processing_spreads | product vs input cost with margin band, daily margin bars (worth/thin/loss) | recipe + ratio, margin now, 30 d mean, days worth it |
| 8 | progression_wave | supply index and price index per level band (item's band thick) | band, price change, supply change, turning day |
| 9 | correlations | both items' price index, correlation by lag | pair, correlation, lag, days |
| 10 | vendor_floor | item hourly min with vendor price line, near hours by hour | vendor price, now, lowest ratio, near share |
| 11 | build_effects | item price/supply around the build (`vLine` at 0), median excess per group | build, change, placebo, excess |
| 12 | inflation | index per group (+ the item), divergence | group, price change, weight, contribution, fits |

## Movers & outliers

- `movers(range)` with range 24h / 7d / 30d: price = median hourly min (24 h: the last 3 hours
  against the same 3 hours a day earlier; 7 d / 30 d: the last full CET day against the full day
  that many days earlier, or the archive's first full day when it is shorter: the sub says which
  days). Items with fewer than 10 sales/day are left out (the sub says so). Six risers, six
  fallers: `{id, name, spark (hourly or daily prices), dir, price (latest snapshot min buyout),
  change, supply ("−62 % supply"), sales}`.
- `mispricings_now(threshold)`: events of the `mispricings` job in the last 24 h of scans, the
  latest per item, whose min is below `threshold` x the usual price (snapshot 30-day median).
  Row: item + its first group, lowest buyout (event min), usual, discount (change), range bar
  (typical = median scan p25..p75 over the 24 h, usual tick, current diamond), quantity listed at
  that scan, seen (local time). Thresholds below 50 / 60 / 70 / 80 %, default 70 %.
- Item names link to Item detail; the overview's "All movers and outliers →" opens the view.

## Screenshot band (task 3)

Headless Edge (`--headless=new --window-size=W,H`) lays the page out at a smaller viewport
(1890 x 985 for 1920 x 1080) and the PNG is W x H, so the app (100 vh) ends early and the rest is the
canvas background. The app's own layout fills its window; the fix belongs in `screenshot.py`.
