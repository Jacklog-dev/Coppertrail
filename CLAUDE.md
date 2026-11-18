# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Since 2026-11-18 the only data source is Blizzard's Game Data API (spec `docs/superpowers/specs/2026-11-18-blizzard-source-design.md`, plan `docs/superpowers/plans/2026-11-18-blizzard-source.md`; WP0 to WP5 and the tree part of WP7 are done, the history rewrite, local cleanup and end-to-end check are open). The hourly and nightly workflows run in the private data repo. The GUI (pywebview + HTML/CSS/JS, no Qt), all four views, all 12 pattern jobs and the Windows exe build work on the new tables. The archive starts on 2026-11-18, so most patterns report `needs_days` for now (`min_days`: 7 for rhythm, 21 for correlations and reversion, 28 for weekday). GUI specs: `2026-11-17-webview-gui-design.md`, `-gui-groundwork-design.md`, `-market-item-views.md`, `-patterns-movers-views.md`; pattern specs `2026-11-17-patterns-batch-a.md` and `-batch-b.md` (written for the old tables; the Blizzard spec says what changed). Next steps: `docs/superpowers/plans/2026-11-18-next-steps.md`. Branches: session branches merge into `dev`; `main` is a release (major version bump, exe, GitHub tag) and only on Jack's call. **`private/handover/HANDOVER.md` is the product spec. Read it before you start any work.** Section 8b is the visual design.

## Changelog

Every push to `main` adds its changes to `CHANGELOG.md`: short bullet points only, no prose, no dates. Bullets go under the current version heading (`## 0.0.1 [Core]`); start a new version heading only when Jack names one.

## Commands

The toolchain is [uv](https://docs.astral.sh/uv/) with Python 3.12 (pinned in `.python-version`).

```bash
uv sync                                   # create .venv, install deps and dev tools
uv run pytest -q                          # tests (offline, mocked HTTP)
uv run ruff check .                       # lint
uv run ruff format .                      # format
uv run python -m coppertrail.collector --data-dir DIR hourly    # fetch the latest snapshot, write its hour
uv run python -m coppertrail.collector --data-dir DIR nightly   # rebuild selection, refresh master data, prune window
uv run python -m coppertrail.ui                       # the GUI window (--data-dir DIR for one session, --size WxH)
uv run python -m coppertrail.ui --dev --port 8765     # serve the page on 127.0.0.1 for a normal browser
uv run python -m coppertrail.ui --screenshot shot.png # headless Edge screenshot (--size, --sample, --data-dir)
uv run python -m coppertrail.ui --sample              # style sample page (combine with --dev or --screenshot)
uv run python -m coppertrail.ui.webtheme              # regenerate web/css/tokens.css after editing tokens.py
uv run python scripts/build_exe.py                    # Windows build: dist/Coppertrail.exe (--console keeps a console for debugging)
uv run python -m coppertrail.patterns list            # registered pattern jobs
uv run python -m coppertrail.patterns run KEY         # basis line + top rows (--group NAME, --days N, --from/--to, --csv FILE)
uv run python -m coppertrail.patterns baseline        # baseline definitions recomputed
```

Collector notes:
- The data dir defaults to `$COPPERTRAIL_DATA`, or `./private` if that is unset. It is the data repo's `main` checkout; the `window` branch is checked out in `<data-dir>/window/`. Settings come from `<data-dir>/collector.toml` (`[blizzard]`, `[selection]`, `[retention]`, field names in `coppertrail/collector/config.py`).
- Credentials: `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET`, otherwise `blizzard.toml` (table `[blizzard]`, `client_id`, `client_secret`) in the config folder. Never log, print or commit either, nor the token.
- Exit codes: 0 ok or not modified, 1 failed, 2 another run holds the lock (`<data-dir>/.lock`).
- Main (our own conclusions, kept for good): `hourly/<day>/<HH>.parquet` (per-item quantiles, quantity, sales estimate; written once), `house/<day>/<HH>.parquet` (whole house per snapshot), `selection/<day>.parquet`, `builds/<day>.parquet`. Every row a source fed carries `source`.
- Window (copied unchanged from Blizzard, at most `copied_days` = 30, rebuilt nightly as one orphan commit and force-pushed): `blizzard/items/<day>.parquet`, `blizzard/recipes/<day>.parquet`. A new source gets its own folder there.
- The previous listings for the sales estimate live in `<data-dir>/.state/` (Actions cache in the workflow). Missing, from another house or older than 6 h: the sales columns are NULL.
- Source-specific code stays in `collector/blizzard.py`, `listings.to_frame` and `master.py`; summaries, sales, selection, query and patterns work on neutral frames.

Query and pattern notes:
- `coppertrail/query/series.py`: `hourly`, `house`, `items`, `item_details`, `recipes`, `builds`, `latest_per_item` (newest hour plus 7/30-day medians, 30-day low/high, `sales_per_day`), each a pandas frame. Item ids and an inclusive UTC day range (as `filtering.date_window` returns it) select rows; only day folders inside the range are read. Timestamps are tz-aware UTC (the DuckDB session is set to UTC). Missing tables give typed empty frames.
- `coppertrail/patterns/base.py`: a job is `fn(ctx: Context) -> PatternResult`, registered with `@pattern(key, number=, title=, min_days=, data=, method=)` and imported in `patterns/__init__.py`. `run(key, ctx)` fills the basis (days used, first/last day, method) and skips the job when the archive is shorter than `min_days` (`needs_days`, `ready_on`). Jobs read only through `Context` and return `ranked` (best first), `charts` (named frames) and, for patterns 3/4/5, `events` in `EVENT_COLS` (`item_id, at, type, detail, magnitude`). No GUI imports in `patterns/`.
- Baseline definitions (`patterns/baseline.py`): top 300 by sales/day x min buyout with at least 20 sales/day (our sales estimate); flip = per-item median over nights of the evening 21-01 mean against the next morning's 07-13 mean minus 5 %; trend = first against last full CET day (at least 20 hours). Local times are Europe/Berlin.

GUI notes:
- No Qt, ever (Jack's rule): a test fails if PySide/PyQt/qtpy/pyqtgraph appear in `uv.lock` or as imports. `[tool.uv] environments` limits the lock to win32/linux/darwin because pywebview lists qtpy for OpenBSD.
- pywebview sits in the `gui` extra, pulled in by the dev group. The collector workflow runs `uv sync --no-dev`, so it does not install it. Backends: EdgeChromium (WebView2) on Windows, GTK on Linux, Cocoa on macOS; never `gui="qt"`.
- `coppertrail/ui/`: `bridge.py` (all GUI data as JSON-able dicts, Qt- and pywebview-free, `Bridge.EXPOSED` lists what JS may call), `app.py` (window, CLI, `AppApi` adds folder picker, credit link and a threaded pull that reports via a `pull` event), `devserver.py` (127.0.0.1-only HTTP server for `--dev`/`--screenshot`, never a normal start), `pull.py` (`git pull --ff-only`, never raises), `screenshot.py` (headless Edge), `webtheme.py` (tokens.py -> `web/css/tokens.css`), `tokens.py`, `format.py`.
- Windows exe: PyInstaller (dev group only, so not in the collector's `--no-dev` sync) runs `packaging/coppertrail.spec` on `packaging/launch.py`: one windowed onefile `dist/Coppertrail.exe` (~80 MB, `build/` and `dist/` gitignored), icon `packaging/coppertrail.ico` (rendered from `web/icons/app.svg`). It bundles `coppertrail/ui/web/` only; `scripts/build_exe.py` deletes the exe if the bundle holds `.parquet`/`.duckdb` files (pyarrow's test fixtures are filtered out in the spec), Qt, or lacks the front end. Frozen, `devserver.web_dir()` reads from `sys._MEIPASS` and the default data folder is `private\` next to the exe; otherwise the folder picker sets it. Cold start to overview about 7 s. `.github/workflows/build-exe.yml` builds it on a `v*` tag push and attaches it to that release (or as an artifact on a manual run); tags and releases stay Jack's call. Debug a frozen window with `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` (DevTools protocol on 127.0.0.1).
- `coppertrail/ui/web/`: plain HTML/CSS/ES modules, no build step, no Node. `js/api.js` is the only way to Python: `call(name, ...args)` uses pywebview's `js_api` in the app and `POST /api/<name>` on the dev server (it tells them apart with `GET /api`, because pywebview injects `window.pywebview` after modules start). pywebview gets a facade (`js_facade`) with only the exposed methods, since it walks every public attribute of `js_api`.
- `web/css/tokens.css` is generated and committed; `test_webtheme.py` fails when it is stale. CSS and JS outside it must not contain hex colours or font names (`test_web_offline.py`), and pages must load nothing remote (fonts via `@font-face`, uPlot 1.6.31 vendored in `web/vendor/`, CSP meta in every page).
- JS writes data strings with `textContent` (the `el()` helper in `js/dom.js`), never `innerHTML`. Display strings come from the bridge (`format.py`); the only JS formatters are chart axis values (`axisCoins`, `axisCount`, `axisPercent`, `axisSigned` in `coins.js`; category, hour and " h" offset x labels in `charts.js`) and chart dates (`charts.js`, en-GB, Europe/Berlin).
- `coppertrail/query/`: query layer and user state. `catalog.py` (items with the latest hourly price, archive status), `groups.py` (item groups: ids, name globs, exclusions; starter groups), `settings.py` (data folder and filters), `filtering.py` (apply filters, resolve the date range, clamped to the archive).
- User settings and groups live in `%APPDATA%\Coppertrail` (or `~/.config/coppertrail`), never in the data repo. `$COPPERTRAIL_CONFIG` overrides the folder; tests use it, and so should any manual `--dev` session that clicks filters, or it changes Jack's real settings.
- The filter bar and group editor re-render their DOM on every state change; they remember the open popover and the focused field (`data-focus`) and restore both.
- Caudex Regular has equal-width digits; Caudex Bold does not (narrow "1"), so keep numeric columns at weight 400. Caudex lacks ▲ ▼ ●: dots and coin marks are CSS circles, arrows come from the font fallback in `--type-*-family` (Segoe UI Symbol on Windows).

## Verified API facts (probes 2026-11-18, details in the Blizzard spec)

- Token: `POST https://oauth.battle.net/token` (client credentials, basic auth). Requests go to `https://eu.api.blizzard.com` with a bearer token, `namespace=dynamic-forever-eu` or `static-forever-eu` (fallback `static-classic1x-eu` for item details), `locale=en_GB`.
- House 111 under ruleset 2 is Normal Alliance EU. The house index needs its trailing slash: `/data/wow/ruleset/2/auctions/`. Listings: `/data/wow/ruleset/2/auctions/111` and `.../111/commodities`.
- Snapshots update once an hour at about :22:5x UTC. `If-Modified-Since` gives 304; a 200 with an unchanged `Last-Modified` counts as not modified.
- Prices are copper per unit (int64): commodities `unit_price`, items `buyout / quantity`. Quantiles are weighted by quantity; bid-only listings count in quantity but not in prices.
- Item lookups hit 429 at 10 parallel requests; 4 parallel with backoff work. About 185 listed items are unknown to Blizzard (kept as unclassified).

Coppertrail is a local auction house analysis tool for WoW Forever (Normal Alliance EU). It collects hourly summaries from Blizzard's Game Data API into a private Parquet archive, runs pattern jobs over it, and shows the results in a desktop GUI. Code, comments and conversation are in English.

## Repositories: code public, data private

| Repo | Visibility | Holds |
|---|---|---|
| https://github.com/Jacklog-dev/Coppertrail | public | Python package `coppertrail` (collector, pattern jobs, GUI) |
| https://github.com/Jacklog-dev/Coppertrail_Database | private | `hourly.yml` (cron `35 * * * *`), `nightly.yml` (00:50 UTC), `collector.toml`, handover, the Parquet files on `main` and `window` |

- **Never commit collected data to the public repo**: no auction data in a commit, test fixture, log line or Actions artifact. Fixtures are hand-made.
- Blizzard's terms: data copied from the API is kept at most 30 days (Jack's reading: our hourly summaries and sales estimate are our own and kept; `summary_retention_days` can delete them if Blizzard says otherwise). Blizzard is named as the source without suggesting endorsement (README and the GUI status strip). At most 36,000 requests per hour.
- The workflows run only in the private data repo. Nothing in the public repo may name or reference the private repo except the README's credit link target.
- **Local layout:** `private/` is a clone of `Coppertrail_Database`, gitignored here (deliberately not a submodule). The handover and design package are in `private/handover/` (index in its `README.md`). Run git commands for data and handover inside `private/`. Until plan task 7.2 is done, the new clone sits in `private-next/` and `private/` is the old one.

## Architecture (see HANDOVER sections 2, 8 and 8a)

- **Stack:** Python 3.12, Parquet queried with DuckDB, pywebview (WebView2) with plain HTML/CSS/JS and uPlot. No Qt.
- **Collector:** a platform-neutral CLI (Windows, Linux/Raspberry Pi, GitHub Actions); the scheduler is a thin wrapper around it. Hour files are write-once, so a rerun of the same snapshot writes nothing.
- **Pattern jobs:** plain functions that return data frames, kept out of widget code so they are testable and callable from a CLI. Each one reports how many days of data it rests on.
- **GUI:** reads the local data directory only through the DuckDB query layer. Its only network action is the explicit "Pull latest data": `git pull --ff-only` on main and a reset of `window/` to `origin/window`.

## Design rules (HANDOVER 8b, enforce in review)

- All colours, fonts and sizes come from `coppertrail/ui/tokens.py` (copied from `private/handover/ui/tokens.py`) and the generated `web/css/tokens.css`. CSS and JS must not hard-code colours or font names.
- Almendra is used only for h1 and card titles, always uppercase. Everything else is Caudex.
- One 1 px border per panel. No ornaments, shadows, gradients or textures.
- Copper means "selected or primary" only. Coin colours are for price values only.
- Rising and falling are never shown by colour alone: always ▲/▼ plus a sign, with a real minus sign (−).
- No Blizzard or WoW assets, fonts (Friz Quadrata) or logos, and no "Warcraft" in the name.
- The mock-ups in `private/handover/mockups*/` are the visual source of truth. Their numbers are invented sample data.

## Limits

- Read-only use of the Blizzard API.
- Do not create accounts, repos, keys or secrets without Jack's say-so.
- No bot actions in the game and no real-money gold trading.
