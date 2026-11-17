# Coppertrail: plan to complete the app

## Context

Done: collector + daily GitHub Actions run (HANDOVER steps 1–3a), GUI theme and window frame (6.1, 6.2). Archive holds hourly data from 2026-11-09 on.
Not done (HANDOVER section 9): **step 4** baseline reproduction, **step 5** all 12 pattern jobs, **6.3** the four real views, **6.4** states + responsive rules, **step 7** own scans.
Gaps found while reading the code:
- No time-series query layer: `coppertrail/query/` only knows the catalogue (latest snapshot), not `hourly`/`scans`/`economy` series.
- The collector stores no vendor price (pattern 10, the item detail "Vendor floor"), no recipes (`/v1/crafting`, pattern 7), no build events (pattern 11).
- `/api/catalog` subclasses are still unverified (needed for subclass filtering and group building).

Decisions (Jack, 2026-11-17): build **all 12 patterns**, the ones without enough history show the "Needs N more weeks" state; **own scans = research spike only**; bigger work runs in **parallel sessions** (own worktree and branch each) that Jack merges.

## How the work is split

Rule for parallel sessions: two sessions never touch the same files at the same time. The ownership is:

| Area | Owner |
|---|---|
| `coppertrail/collector/`, its tests | collector session |
| `coppertrail/patterns/`, its tests | pattern sessions (one at a time) |
| `coppertrail/ui/` (incl. `bridge.py`, `web/`), its tests | GUI sessions (one at a time) |
| `coppertrail/query/`, `CLAUDE.md`, `README.md`, plans/specs | this session only |

Each session: brainstorm → short spec in `docs/superpowers/specs/` → plan → TDD with subagent-driven development → `/code-review` → finish on its branch. This session reviews each branch's diff, then merges into `main` on Jack's word and updates CLAUDE.md.

## Phase 0 — Foundation (this session, sequential; everything else depends on it)

1. **Series query layer** `coppertrail/query/series.py`: DuckDB over the day files, all functions take item ids + resolved date range (reuse `filtering.py` range resolution, `catalog.py` connection pattern) and return pandas/pyarrow frames: `hourly(ids, start, end)`, `scans(...)`, `economy(...)`, `snapshots(...)`, `archive_days()` (days of data, first/last day). Tests on small synthetic Parquet fixtures.
2. **Pattern contract** `coppertrail/patterns/base.py`:
   - `PatternResult` dataclass: `key`, `title`, `days_used`, `first_day`, `last_day`, `items_checked`, `items_hit`, `method_note`, `ranked` (frame), `charts` (dict of frames), `needs_days` / `ready_on` when history is too short. This fills the Patterns "basis line" (HANDOVER 8b) and the "too little history" state.
   - Registry (`REGISTRY: dict[str, PatternSpec]` with `min_days`, `data` = hourly/scans/daily/recipes/builds) and `run(key, ids, start, end, data_dir)`.
   - CLI `python -m coppertrail.patterns list | run <key> [--items group] [--csv out]`.
   - Event schema shared by patterns 3/4/5 (`item_id, at, type, detail, magnitude`) so the GUI's event markers and "What changed" read one shape.
3. **Baseline (HANDOVER step 4)**: `coppertrail/patterns/baseline.py` reproducing section 5 (daily-rhythm index table, evening→morning flip −3.6 % / −8.6 %, weekly trend, outlier clustering) on 2026-11-09…16. If numbers differ, find out why before Phase 1 (subagent for the investigation if it gets deep).
4. Update CLAUDE.md (query layer, pattern contract, CLI). Commit.
5. **Remind Jack**: `API_ARCHIVE_UNTIL` is 2026-12-09; ask whether AHledger answered.

## Phase 1 — three parallel sessions

**S1 Collector extensions** (collector only)
- Verify `/api/catalog?class=…` subclasses; if present, store `subclass` in `items`.
- Vendor price: find which endpoint gives it (tooltip/catalog), add `vendor_price` to `items`.
- Recipes: `/v1/crafting/{market}` (csv) into a `recipes` table (recipe, product id/qty, reagent ids/qty); fetched once per run, cheap.
- Build events: verify the `/feed/builds.xml` URL, store a `builds` table.
- Keep the 30 req/min throttle; tests with mocked HTTP; update the private workflow only if run time grows (Jack approves workflow changes).

**S2 Patterns batch A** (patterns only, data already there): 1 Daily rhythm (hourly profile per item, buy 22:00 / sell 07:00 backtest after 5 % cut, detrended, wins/nights, confidence), 3 Mispricings (min below rolling p25, time to correction; per-scan), 4 Supply shocks (quantity jumps, price lag), 5 Buyout and reset (quantity drop + min jump; per-scan), 8 Progression wave (per level band, supply-growth turning point), 12 Inflation (turnover-weighted basket index for farmable / scarce / vendor-tied groups, divergence, gold listed from `economy`; population skipped — CSV blocked). Each with ranked frame, chart frames, sample size, tests on synthetic series with a known planted pattern.

**S3 GUI groundwork** (ui only, no pattern data needed): states from 8b (no data, stale banner + chart shading, filter matches nothing with "drop this filter" hint, loading skeleton + progress, pull failed), responsive rules (≤1440 icon rail and "More" button, ≥2400 third column), chart building blocks in `charts.js` (linked x-axes via `cursor.sync`, event markers in a `draw` hook, bands, bars with 28 % gap, flipping tooltip, zoom + reset button, sparkline, range bar). Check every state with `--screenshot` against `private/handover/mockups*/`.

**S4 Own-scan research spike** (read-only, writes `docs/own-scans-research.md` only): what the AHledger addon writes to SavedVariables (path, format, `/ahl status`), whether another scan addon fits, what the Forever client API allows for full scans, and an importer sketch (`source = own_scan` into `hourly`/`scans`). Recommendation for Jack, no code.

Merge S1–S4 when done.

## Phase 2 — two parallel sessions

**S5 Patterns batch B** (patterns only, needs S1 merged): 7 Processing spreads (recipes × reagent min buyouts vs product min, margin series, days worth it; leather chain first), 10 Vendor floor, 11 Patch/build effects (price reaction window around builds), and the gated ones 2 Weekday/raid reset (min 28 days, ready ≈ 7 Dec), 6 Mean reversion (21 days, ≈ 30 Nov), 9 Correlated items (21 days, lagged cross-correlation). Gated jobs return `needs_days`/`ready_on` until the archive is long enough, but run on synthetic data in tests.

**S6 GUI: Market overview + Item detail** (ui only, needs Phase 0 + S2 + S3 merged): bridge methods returning JSON chart data and display strings via `format.py`; overview (4/6 tiles, price index from pattern 12, daily rhythm from pattern 1, total supply, gold listed, What changed from events); item detail (item list panel with sort, header with days of history, 5 tiles, price + supply linked charts with events and vendor floor, hour-of-day profile, events table, "Add to group" / "Show in patterns").

## Phase 3 — one GUI session

**S7 GUI: Patterns + Movers & outliers** (needs S5 + S6 merged): Patterns template (tab bar with "needs data" chips, basis line, charts left / ranked list right, row click charts the item) and per-pattern chart sets for all 12 (Daily rhythm and Processing spreads as in the mock-ups, the others follow the template); Movers & outliers (24 h / 7 d / 30 d, risers/fallers with sparklines, mispricings table with range bars and threshold).
Could split into two sessions if Phase 2 lands early, but both edit `bridge.py` and `views.js`, so keep it one.

## Phase 4 — finish (this session)

- End-to-end check on the real archive: every view, every pattern tab, every state, compact and ultrawide sizes, screenshots for Jack.
- `/code-review` over the whole diff since today; fix.
- README (features, screenshots without data values, AHledger credit, no data shipped), CLAUDE.md status.
- Parchment theme only if Jack asks (6.5). Decide own-scan importer from S4's report.

## Timeline facts to keep in mind

- Archive starts 2026-11-09: 21 days ≈ 30 Nov, 28 days ≈ 7 Dec.
- API archiving stops 2026-12-09 unless Jack decides otherwise; after that only own scans extend the archive.

## Verification

- Every session: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`; tests stay offline; `test_no_qt.py`, `test_web_offline.py`, `test_webtheme.py` stay green.
- Patterns: `uv run python -m coppertrail.patterns run <key>` on `./private` prints the basis line and top rows; baseline numbers match HANDOVER section 5.
- Collector: `uv run python -m coppertrail.collector --data-dir <tmp> run --max-items 3` live smoke test with the new tables.
- GUI: `uv run python -m coppertrail.ui --screenshot shot.png --size 1920x1080` (and 1280x800, 2560x1080), compared with the mock-ups; manual `--dev` sessions with `$COPPERTRAIL_CONFIG` pointing at a temp folder.
