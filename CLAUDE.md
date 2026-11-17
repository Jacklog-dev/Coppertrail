# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

The collector exists (HANDOVER section 9, steps 1 to 3). The GUI theme (step 6.1) and window frame (step 6.2: nav rail, filter bar, group editor, status strip) exist, rebuilt on pywebview + HTML/CSS/JS on 2026-11-17 (no Qt, see `docs/superpowers/specs/2026-11-17-webview-gui-design.md`); Market overview and Item detail are built on real data (`docs/superpowers/specs/2026-11-17-market-item-views.md`); Patterns and Movers & outliers are still placeholders. The states from 8b, both breakpoints and the chart building blocks exist (`docs/superpowers/specs/2026-11-17-gui-groundwork-design.md`). The series query layer, the pattern contract and CLI, the section 5 baseline (step 4) and all 12 pattern jobs exist (specs `2026-11-17-patterns-batch-a.md` and `-batch-b.md`); 2, 6 and 9 wait for 21 to 28 days of history, and 7, 10 and 11 need the recipes, builds and item details the collector fills from 2026-11-18 on. Own scans: research only, `docs/own-scans-research.md`. The plan for the rest is `docs/superpowers/plans/2026-11-17-complete-the-app.md`: parallel sessions with file ownership (collector / patterns / ui); `query/`, CLAUDE.md and README stay with the coordinating session. **`private/handover/HANDOVER.md` is the spec. Read it before you start any work.** Section 8b is the visual design, and section 9 is the order of work.

## Changelog

Every push to `main` adds its changes to `CHANGELOG.md`: short bullet points only, no prose, no dates. Bullets go under the current version heading (`## 0.0.1 [Core]`); start a new version heading only when Jack names one.

## Commands

The toolchain is [uv](https://docs.astral.sh/uv/) with Python 3.12 (pinned in `.python-version`).

```bash
uv sync                                   # create .venv, install deps and dev tools
uv run pytest -q                          # tests (offline, mocked HTTP)
uv run ruff check .                       # lint
uv run ruff format .                      # format
uv run python -m coppertrail.collector run            # one collector run into ./private (~40 min)
uv run python -m coppertrail.collector --data-dir DIR run --max-items 3   # quick live smoke test
uv run python -m coppertrail.collector gaps           # gap report for the latest watchlist
uv run python -m coppertrail.ui                       # the GUI window (--data-dir DIR for one session, --size WxH)
uv run python -m coppertrail.ui --dev --port 8765     # serve the page on 127.0.0.1 for a normal browser
uv run python -m coppertrail.ui --screenshot shot.png # headless Edge screenshot (--size, --sample, --data-dir)
uv run python -m coppertrail.ui --sample              # style sample page (combine with --dev or --screenshot)
uv run python -m coppertrail.ui.webtheme              # regenerate web/css/tokens.css after editing tokens.py
uv run python -m coppertrail.patterns list            # registered pattern jobs
uv run python -m coppertrail.patterns run KEY         # basis line + top rows (--group NAME, --days N, --from/--to, --csv FILE)
uv run python -m coppertrail.patterns baseline        # HANDOVER section 5 recomputed, side by side
```

Collector notes:
- The data dir defaults to `$COPPERTRAIL_DATA`, or `./private` if that is unset. Optional overrides go in `<data-dir>/collector.toml` under a `[collector]` table, with the field names from `coppertrail/collector/config.py`.
- Exit codes: 0 ok or partial, 1 failed, 2 another run holds the lock, 3 the `API_ARCHIVE_UNTIL` cutoff was reached or archiving is disabled.
- Each fetched item is staged in `<data-dir>/.staging/<run_id>/` and merged into the day files at the end of the run. Rerunning after a crash resumes the run, as long as it started within the last 12 h.
- Day-file tables: `hourly`, `scans`, `snapshot`, `economy`, `items`, `watchlist`, `runs`, `gaps`, `population`, `recipes`, `builds`. Logs go to `<data-dir>/logs/`.
- Run order: watchlist, economy, population, recipes, builds, hourly, scans, item details. Recipes and builds are one request each and soft errors. Item details (`subclass`, `required_level`, `vendor_price`) are backfilled at most 200 items per run (`item_details_per_run`), so the first ~5 runs take about 7 minutes longer (workflow `timeout-minutes: 90`). Details: `docs/superpowers/specs/2026-11-17-collector-master-data-design.md`.

Query and pattern notes:
- `coppertrail/query/series.py`: `hourly`, `scans`, `snapshots`, `latest_snapshot`, `economy`, `items`, `recipes`, `builds`, `item_details` (newest non-null subclass, required level, vendor price per item), each a pandas frame. Item ids and an inclusive UTC day range (as `filtering.date_window` returns it) select rows; only day files inside the range are read. Timestamps are tz-aware UTC (the DuckDB session is set to UTC, else TIMESTAMPTZ comes back in local time). Missing tables give typed empty frames.
- `coppertrail/patterns/base.py`: a job is `fn(ctx: Context) -> PatternResult`, registered with `@pattern(key, number=, title=, min_days=, data=, method=)` and imported in `patterns/__init__.py`. `run(key, ctx)` fills the basis (days used, first/last day, method) and skips the job when the archive is shorter than `min_days` (`needs_days`, `ready_on`). Jobs read only through `Context` and return `ranked` (best first), `charts` (named frames) and, for patterns 3/4/5, `events` in `EVENT_COLS` (`item_id, at, type, detail, magnitude`). No GUI imports in `patterns/`.
- Baseline definitions (`patterns/baseline.py`): top 300 by sales/day x min buyout with at least 20 sales/day (only watchlist items have hourly data, so fewer remain); flip = per-item median over nights of the evening 21-01 mean against the next morning's 07-13 mean minus 5 %; trend = first against last full CET day (at least 20 hours). Local times are Europe/Berlin.

GUI notes:
- No Qt, ever (Jack's rule): a test fails if PySide/PyQt/qtpy/pyqtgraph appear in `uv.lock` or as imports. `[tool.uv] environments` limits the lock to win32/linux/darwin because pywebview lists qtpy for OpenBSD.
- pywebview sits in the `gui` extra, pulled in by the dev group. The collector workflow runs `uv sync --no-dev`, so it does not install it. Backends: EdgeChromium (WebView2) on Windows, GTK on Linux, Cocoa on macOS; never `gui="qt"`.
- `coppertrail/ui/`: `bridge.py` (all GUI data as JSON-able dicts, Qt- and pywebview-free, `Bridge.EXPOSED` lists what JS may call), `app.py` (window, CLI, `AppApi` adds folder picker, credit link and a threaded pull that reports via a `pull` event), `devserver.py` (127.0.0.1-only HTTP server for `--dev`/`--screenshot`, never a normal start), `pull.py` (`git pull --ff-only`, never raises), `screenshot.py` (headless Edge), `webtheme.py` (tokens.py -> `web/css/tokens.css`), `tokens.py`, `format.py`.
- `coppertrail/ui/web/`: plain HTML/CSS/ES modules, no build step, no Node. `js/api.js` is the only way to Python: `call(name, ...args)` uses pywebview's `js_api` in the app and `POST /api/<name>` on the dev server (it tells them apart with `GET /api`, because pywebview injects `window.pywebview` after modules start). pywebview gets a facade (`js_facade`) with only the exposed methods, since it walks every public attribute of `js_api`.
- `web/css/tokens.css` is generated and committed; `test_webtheme.py` fails when it is stale. CSS and JS outside it must not contain hex colours or font names (`test_web_offline.py`), and pages must load nothing remote (fonts via `@font-face`, uPlot 1.6.31 vendored in `web/vendor/`, CSP meta in every page).
- JS writes data strings with `textContent` (the `el()` helper in `js/dom.js`), never `innerHTML`. Display strings come from the bridge (`format.py`); the only JS formatters are chart axis coins (`axisCoins`) and chart dates (`charts.js`, en-GB, Europe/Berlin).
- `coppertrail/query/`: query layer and user state. `catalog.py` (items with the latest snapshot price, archive status), `groups.py` (item groups: ids, name globs, exclusions; starter groups), `settings.py` (data folder and filters), `filtering.py` (apply filters, resolve the date range, clamped to the archive).
- User settings and groups live in `%APPDATA%\Coppertrail` (or `~/.config/coppertrail`), never in the data repo. `$COPPERTRAIL_CONFIG` overrides the folder; tests use it, and so should any manual `--dev` session that clicks filters, or it changes Jack's real settings.
- The filter bar and group editor re-render their DOM on every state change; they remember the open popover and the focused field (`data-focus`) and restore both.
- Caudex Regular has equal-width digits; Caudex Bold does not (narrow "1"), so keep numeric columns at weight 400. Caudex lacks ▲ ▼ ●: dots and coin marks are CSS circles, arrows come from the font fallback in `--type-*-family` (Segoe UI Symbol on Windows).

## Verified API facts (2026-11-16, 2026-11-17)

- `GET /v1/items/{id}?game=forever` (one id per request, comma lists are rejected) gives `itemSubclass` ("Leather", "Herb", "Metal & Stone", "Cloth", ...), `vendorSell` (copper) and `requiredLevel`. `/v1/tooltip` has neither subclass nor vendor price.
- `GET /v1/crafting/{market}?all=true&limit=3000` (JSON) returns all 2,227 recipes with `recipe.{spellId,name,profession,skillRequired,acquisition}`, `result.{id,name,qtyMin,qtyMax}`, `reagents[].{id,name,qty}`. Without `all=true` only 500 priced recipes come back; `format=csv` has no reagents; `limit` above 3000 is rejected.
- `https://ahledger.com/feed/builds.xml` is RSS 2.0; titles look like "WoW Forever [stage ]X.Y.Z (build N): ...".
- `ahledger.com/api/catalog?class=trade-goods` has subclasses but no vendor price and sits behind the website; not used.

- Price table columns 5 to 8 are the 7-day median, 30-day median, 30-day low and 30-day high. They are documented on the developers page and match `/prices` `latest`.
- A `range=24h` point has the same fields as a 7d point: `{t, min, median, p25, p75, quantity, auctions}`, with one point per full scan.
- The price table has no quality field. Quality comes from `/v1/tooltip` (100 items per request) and is cached in `items/`.
- The population CSV on `ahledger.com` sits behind a Vercel bot check that scripts do not pass. The collector logs it as skipped. Do not try to get around the check.

Coppertrail is a local auction house analysis tool for WoW Forever (market `forever.normal.alliance.eu`). It collects price history from the AHledger API into a private Parquet archive, runs pattern jobs over it, and shows the results in a desktop GUI. Code, comments and conversation are in English.

## Repositories: code public, data private

| Repo | Visibility | Holds |
|---|---|---|
| https://github.com/Jacklog-dev/Coppertrail | public | Python package `coppertrail` (collector, pattern jobs, GUI) |
| https://github.com/Jacklog-dev/Coppertrail_Data | private | Scheduled GitHub Actions workflow plus the Parquet day files |

- **Never commit collected data to the public repo.** Doing so would redistribute AHledger data, which their terms forbid. Put the data directory in `.gitignore` from the first commit.
- The README must credit "Prices from AHledger" with a link and state that the repo ships no data. The GUI status strip shows the same credit at all times.
- The private repo's workflow checks out the public code, runs the collector once a day (about 40 min, with `timeout-minutes` set) and commits the new day files to itself. It lives in `private/.github/workflows/collect.yml`: its first step, before any checkout, disables the workflow once the date is past `API_ARCHIVE_UNTIL` (2026-12-09) and fails that one run so Jack gets the e-mail. No further runs use minutes. Re-enable (`gh workflow enable collect.yml`) only on Jack's word.
- **Local layout:** `private/` is a separate clone of `Coppertrail_Data`, gitignored here (deliberately not a submodule: the public repo must not reference the private one). The handover and design package are in `private/handover/` (index in its `README.md`). Run git commands for data and handover inside `private/`.

## Architecture (planned, see HANDOVER sections 2, 8 and 8a)

- **Stack:** Python 3.12, Parquet queried with DuckDB, pywebview (WebView2) with plain HTML/CSS/JS and uPlot. No Qt.
- **Collector:** a platform-neutral CLI (`python -m collector run`) with no Windows-specific code. The scheduler (GitHub Actions, or Task Scheduler as a fallback) is only a thin wrapper around it.
  - Runs must be idempotent. Upsert on `HOURLY(item_id, hour)` and `SCAN_POINT(item_id, observed_at)`, and commit per item so an interrupted run resumes cleanly.
  - It runs without an API key: throttle to 30 requests/min and honour `Retry-After` on 429 and 503.
  - Every row carries `source` (`api` or `own_scan`).
  - API archiving stops at `API_ARCHIVE_UNTIL` (default 2026-12-09) because AHledger's terms change. Whether to continue past that date is Jack's decision, so raise it with him before then. Never let it run on silently.
- **Storage:** append-only Parquet, one file per day and table (`hourly/`, `scans/`, `snapshot/`, `economy/`). No binary DB file in git.
- **Pattern jobs:** plain functions that return data frames, kept out of widget code so they are testable and callable from a CLI. Each one reports how many days of data it rests on.
- **GUI:** reads the local data directory only through the DuckDB query layer. Its only network action is the explicit "Pull latest data", which runs `git pull` on the data repo.

## Verify before relying on

These are unconfirmed in the handover:

- Price table columns 5 to 8, and the fields of a `range=24h` point: verified 2026-11-16, see above.
- Whether `/api/catalog` provides subclasses.
- Current GitHub free-tier minutes.
- AHledger's terms (https://ahledger.com/developers).

## Design rules (HANDOVER 8b, enforce in review)

- All colours, fonts and sizes come from `coppertrail/ui/tokens.py` (copied from `private/handover/ui/tokens.py`) and the generated `web/css/tokens.css`. CSS and JS must not hard-code colours or font names.
- Almendra is used only for h1 and card titles, always uppercase. Everything else is Caudex.
- One 1 px border per panel. No ornaments, shadows, gradients or textures.
- Copper means "selected or primary" only. Coin colours are for price values only.
- Rising and falling are never shown by colour alone: always ▲/▼ plus a sign, with a real minus sign (−).
- No Blizzard or WoW assets, fonts (Friz Quadrata) or logos, and no "Warcraft" in the name.
- The mock-ups in `private/handover/mockups*/` are the visual source of truth. Their numbers are invented sample data.

## Limits

- Read-only use of AHledger.
- Do not create accounts, repos, keys or secrets without Jack's say-so.
- No bot actions in the game and no real-money gold trading.
