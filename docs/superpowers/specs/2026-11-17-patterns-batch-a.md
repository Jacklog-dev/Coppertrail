# Patterns batch A (S2): patterns 1, 3, 4, 5, 8, 12

Session S2 of `docs/superpowers/plans/2026-11-17-complete-the-app.md`. Owns `coppertrail/patterns/` and its tests only. Definitions reuse `patterns/baseline.py` (CET = Europe/Berlin, `_full_hours`, `trim_mean`, 5 % cut). The archive starts 2026-11-09 (hourly) and 2026-11-15 (scans), so no job claims weekday effects, and confidence labels are capped by the number of nights.

## Shared rules

- One module per job, registered with `@pattern` and imported in `patterns/__init__.py`. Helpers shared by several jobs live in `patterns/common.py` (names, sales/day, CET day, run grouping).
- `ranked`: one row per item, best first, always starting `item_id, name`. Fractions are signed fractions (`-0.12` = 12 % down), durations in minutes or hours with the unit in the column name, hours of day as 0..23 CET.
- `charts`: named frames with an `item_id` column wherever a chart is per item, so the GUI filters by the clicked row.
- `events` (patterns 3, 4, 5): `EVENT_COLS`; `magnitude` is the signed fraction the event is named after; `detail` is a short English sentence.
- Every job sets `items_checked`, `items_hit` and a `note` with its thresholds.

## Jobs

| key | no. | data | min days | hit means |
|---|---|---|---|---|
| `daily_rhythm` | 1 | hourly, snapshot, items | 7 | median detrended night result > 0 and at least 60 % of nights won |
| `mispricings` | 3 | scans, snapshot, items | 1 | at least one scan with min buyout 30 % or more below the rolling 6 h median of p25 |
| `supply_shocks` | 4 | hourly, snapshot, items | 3 | at least one hour with quantity 60 % or more above the prior 24 h median |
| `buyouts` | 5 | scans, snapshot, items | 1 | quantity down 40 % or more and min buyout up 20 % or more from one scan to the next |
| `progression_wave` | 8 | hourly, items | 3 | the item's supply growth flattened after a growth phase |
| `inflation` | 12 | hourly, snapshot, items, economy | 3 | basket item moved the way the hypothesis predicts (scarce up, farmable/vendor down, by 5 %) |

Details:

1. **Daily rhythm.** Index per CET hour for min, p25 and quantity, 100 = the item's centred 25 h rolling mean (as the baseline). Backtest per night: buy at the 22:00 hour's min, sell at the next 07:00 hour's min after the 5 % cut, detrended by dividing by the rolling-mean ratio sell/buy. Confidence: high = 20+ nights and 75 %+ won; medium = 7+ nights and 60 %+ won; else low. Charts `nights` (per item and night), `typical_day` (per item and hour), `market_day` (trimmed mean over items).
2. **Mispricings.** Per item over scans sorted by time; reference = median of `p25` over the prior 6 h (closed left, 6 scans at least). Consecutive flagged scans are one event; it corrects at the first later scan back above the threshold line. Charts `events`, `by_hour`.
3. **Supply shocks.** Per item on full hours; baseline = median quantity of the prior 24 h (12 hours at least). Runs of flagged hours are one shock. Price response = change of min at lag 0..12 h against the prior 24 h median min, the lag with the largest absolute change is reported. Per item also the lagged correlation of hourly log changes of quantity and min (lags -12..12 h). Charts `events`, `response` (per item and lag), `response_all`.
4. **Buyouts.** Scan to scan within 60 min, previous quantity at least 10. Reset = first later scan whose min is back within 10 % of the pre-buyout min. Charts `events`, `by_hour`.
5. **Progression wave.** CET days with at least 12 hourly rows; per item daily mean min and quantity; level bands 1-9, 10-19, ..., 50-59, 60. Band series = median over items of value / first-day value x 100. Turning point = first day after the peak of 2-day smoothed supply growth where that growth drops below a quarter of the peak (peak growth at least 5 %/day). Charts `bands`, `turning_points`.
6. **Inflation.** Groups from the starter definitions in `query/groups.py`: farmable = Herbs + Leather chain + Cloth + Ore and bars minus Scarce goods; scarce = Scarce goods; vendor-tied = a fixed name list in `inflation.py` (thread, dye, vials, flux, vendor drinks, spices, flour, vendor ammo) until vendor prices exist. Daily price = CET-day median of hourly min. Weight = latest sales/day x base-day price, normalised per group; index = weighted mean of price relatives x 100 over items present, base day = first day. Divergence = scarce - farmable (index points). Economy: gold listed (gold), auctions, units with an index on the first day. Population is not available (bot check), not attempted. Charts `index`, `divergence`, `economy`.

## Plan

1. `common.py` helpers; test fixture that hands a job a `Context` with preset frames.
2. Per job: test with a planted pattern and one on flat noise, then the job, then `__init__` import.
3. Run every job on the real archive (`run <key>`), record basis lines in the report.
4. pytest, ruff check, ruff format --check, code review, commit on the branch.
