# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

**Since 2026-11-24 the only data source is the raw data database on the Raspberry Pi** (see below). The private GitHub data repository and its hourly/nightly workflows are deleted; nothing collected before matters. Two separate databases, never linked: the Pi's raw data database (Blizzard's data as sent, 30 days) and "our" database on the PC (our own conclusions, kept forever). The PC only gets what the Pi's `export` hands out. **Next project: design "our" database on the PC** and refactor the collector onto it; it must fill the Item Detail panel. Until then the collector, `ui/pull.py`, the `window/`/`copied-data` notes and the pattern jobs below describe the old GitHub pipeline and have no live data.

The GUI (pywebview + HTML/CSS/JS, no Qt), its four views, the 12 pattern jobs and the Windows exe build exist and are tested on fixtures. GUI specs: `2026-11-17-webview-gui-design.md`, `-gui-groundwork-design.md`, `-market-item-views.md`, `-patterns-movers-views.md`; pattern specs `2026-11-17-patterns-batch-a.md` and `-batch-b.md`. Branches: session branches merge into `dev`; `main` is a release (major version bump, exe, GitHub tag) and only on Jack's call. **`private/handover/HANDOVER.md` is the product spec. Read it before you start any work.** Section 8b is the visual design. (`private/` is now only a local folder; its GitHub repo is gone.)

## Raspberry Pi (raw data database, the only source)

- **Access:** `ssh coppertrail@coppertrail-pi` (key login, passwordless sudo). Raspberry Pi 1 B+: armv6l, 426 MB RAM, 29 GB SD card, Raspberry Pi OS Lite 32-bit (Trixie), Python 3.13, SQLite 3.46. DuckDB, pyarrow and pandas have no armv6 builds, so code that runs on the Pi uses the standard library only. Keep the Pi's work minimal: it stores and hands out bytes, it never summarises.
- **Database:** one file, `/var/lib/coppertrail/raw.sqlite` (WAL). `snapshot`: one row per listing response (`items`|`commodities`, hourly), the body exactly as received (gzip), about 2.8 MB per hour, about 2 GB for 30 days. `item`: one row per item lookup (200 body as received, or a 404 row). `id`/`seq` only grow and are the PC's bookmarks.
- **Jobs:** `coppertrail-raw.timer` at :27 UTC runs `coppertrail_raw.py collect` (deletes rows that would turn 30 days old, then stores new responses; `If-Modified-Since`, retries every 5 min until :55). `coppertrail-items.timer` at :00 runs `items` (item details missing, older than 25 days, or a 404 older than 7 days; stops at :20). Same lock; exit codes 0/1/2. Logs: `journalctl -u coppertrail-raw.service` / `-u coppertrail-items.service`.
- **Export:** `ssh coppertrail@coppertrail-pi "python3 /opt/coppertrail/coppertrail_raw.py export --after-snapshot ID --after-item SEQ"` streams every newer row (JSON header line + body bytes, then an end line). Read-only, no credentials. Format in `pi/README.md`.
- **30-day limit:** if the Pi is off nothing is deleted, which Jack accepts (an off Pi is broken, or the project has ended).
- **Credentials:** `/etc/coppertrail/blizzard.env` (root:coppertrail, 640), set with `sudo bash /opt/coppertrail/set-blizzard-secret.sh` (hidden input, then a token check). Never print or copy that file.
- **Code:** `pi/` (script, units, `install.sh`, `set-blizzard-secret.sh`), tests `tests/test_pi_*.py`. Deploy: copy `pi/` to the Pi, then `sudo bash install.sh` outside :25–:56 and :00–:20 (`--status` shows both timers, the last log lines and the database size). Spec `docs/superpowers/specs/2026-11-24-pi-raw-store-design.md`.
- The raw data lives on the Pi only. Never copy it into this repo (an export for a test goes to a scratch folder and is deleted afterwards).

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

Collector notes (old GitHub pipeline, to be replaced by "our" database on the PC):
- The data dir defaults to `$COPPERTRAIL_DATA`, or `./private` if that is unset. It is the data repo's `main` checkout; the copied data sits in `<data-dir>/window/` (not in git). Settings come from `<data-dir>/collector.toml` (`[blizzard]`, `[selection]`, `[retention]`, field names in `coppertrail/collector/config.py`).
- Credentials: `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET`, otherwise `blizzard.toml` (table `[blizzard]`, `client_id`, `client_secret`) in the config folder. Never log, print or commit either, nor the token.
- Exit codes: 0 ok or not modified, 1 failed, 2 another run holds the lock (`<data-dir>/.lock`).
- Main (our own conclusions, kept for good): `hourly/<day>/<HH>.parquet` (per-item quantiles, quantity, sales estimate; written once), `house/<day>/<HH>.parquet` (whole house per snapshot), `selection/<day>.parquet`, `builds/<day>.parquet`. Every row a source fed carries `source`.
- Copied data (unchanged from Blizzard) is never in git. It lives in `<data-dir>/window/` (`blizzard/items/<day>.parquet`, `blizzard/recipes/<day>.parquet`; a new source gets its own folder) and moves between runs as the `copied-data` Actions artifact (`retention-days: 1`). Both runs prune it at `copied_days - artifact_days` (30 − 1), so no copy anywhere is older than 30 days. `artifact_days` in `collector.toml` must equal the workflows' `retention-days`. Overview with diagrams: `docs/architecture.md`.
- The previous listings for the sales estimate live in `<data-dir>/.state/` (Actions cache in the workflow). Missing, from another house or older than 6 h: the sales columns are NULL.
- Source-specific code stays in `collector/blizzard.py`, `listings.to_frame` and `master.py`; summaries, sales, selection, query and patterns work on neutral frames.

Query and pattern notes:
- `coppertrail/query/series.py`: `hourly`, `house`, `items`, `item_details`, `recipes`, `builds`, `latest_per_item` (newest hour plus 7/30-day medians, 30-day low/high, `sales_per_day`), each a pandas frame. Item ids and an inclusive UTC day range (as `filtering.date_window` returns it) select rows; only day folders inside the range are read. Timestamps are tz-aware UTC (the DuckDB session is set to UTC). Missing tables give typed empty frames.
- `coppertrail/patterns/base.py`: a job is `fn(ctx: Context) -> PatternResult`, registered with `@pattern(key, number=, title=, min_days=, data=, method=)` and imported in `patterns/__init__.py`. `run(key, ctx)` fills the basis (days used, first/last day, method) and skips the job when the archive is shorter than `min_days` (`needs_days`, `ready_on`). Jobs read only through `Context` and return `ranked` (best first), `charts` (named frames) and, for patterns 3/4/5, `events` in `EVENT_COLS` (`item_id, at, type, detail, magnitude`). No GUI imports in `patterns/`.
- Baseline definitions (`patterns/baseline.py`): top 300 by sales/day x min buyout with at least 20 sales/day (our sales estimate); flip = per-item median over nights of the evening 21-01 mean against the next morning's 07-13 mean minus 5 %; trend = first against last full CET day (at least 20 hours). Local times are Europe/Berlin.

GUI notes:
- No Qt, ever (Jack's rule): a test fails if PySide/PyQt/qtpy/pyqtgraph appear in `uv.lock` or as imports. `[tool.uv] environments` limits the lock to win32/linux/darwin because pywebview lists qtpy for OpenBSD.
- pywebview sits in the `gui` extra, pulled in by the dev group. The collector workflow runs `uv sync --no-dev`, so it does not install it. Backends: EdgeChromium (WebView2) on Windows, GTK on Linux, Cocoa on macOS; never `gui="qt"`.
- `coppertrail/ui/`: `bridge.py` (all GUI data as JSON-able dicts, Qt- and pywebview-free, `Bridge.EXPOSED` lists what JS may call), `app.py` (window, CLI, `AppApi` adds folder picker, credit link and a threaded pull that reports via a `pull` event), `devserver.py` (127.0.0.1-only HTTP server for `--dev`/`--screenshot`, never a normal start), `pull.py` (copied-data artifact via `gh`, then `git pull --ff-only`, never raises), `screenshot.py` (headless Edge), `webtheme.py` (tokens.py -> `web/css/tokens.css`), `tokens.py`, `format.py`.
- Windows exe: PyInstaller (dev group only, so not in the collector's `--no-dev` sync) runs `packaging/coppertrail.spec` on `packaging/launch.py`: one windowed onefile `dist/Coppertrail.exe` (~80 MB, `build/` and `dist/` gitignored), icon `packaging/coppertrail.ico` (rendered from `web/icons/app.svg`). It bundles `coppertrail/ui/web/` only; `scripts/build_exe.py` deletes the exe if the bundle holds `.parquet`/`.duckdb` files (pyarrow's test fixtures are filtered out in the spec), Qt, or lacks the front end. Frozen, `devserver.web_dir()` reads from `sys._MEIPASS` and the default data folder is `private\` next to the exe; otherwise the folder picker sets it. Cold start to overview about 7 s. `.github/workflows/build-exe.yml` builds it on a `v*` tag push and attaches it to that release (or as an artifact on a manual run); tags and releases stay Jack's call. Debug a frozen window with `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` (DevTools protocol on 127.0.0.1).
- `coppertrail/ui/web/`: plain HTML/CSS/ES modules, no build step, no Node. `js/api.js` is the only way to Python: `call(name, ...args)` uses pywebview's `js_api` in the app and `POST /api/<name>` on the dev server (it tells them apart with `GET /api`, because pywebview injects `window.pywebview` after modules start). pywebview gets a facade (`js_facade`) with only the exposed methods, since it walks every public attribute of `js_api`.
- `web/css/tokens.css` is generated and committed; `test_webtheme.py` fails when it is stale. CSS and JS outside it must not contain hex colours or font names (`test_web_offline.py`), and pages must load nothing remote (fonts via `@font-face`, uPlot 1.6.31 vendored in `web/vendor/`, CSP meta in every page). The one exception: item icon images from `https://render.worldofwarcraft.com` (CSP `img-src` only; the host lives in Python, never in JS/CSS).
- JS writes data strings with `textContent` (the `el()` helper in `js/dom.js`), never `innerHTML`. Display strings come from the bridge (`format.py`); the only JS formatters are chart axis values (`axisCoins`, `axisCount`, `axisPercent`, `axisSigned` in `coins.js`; category, hour and " h" offset x labels in `charts.js`) and chart dates (`charts.js`, en-GB, Europe/Berlin).
- Item icons: `web/icon-map.json` maps item id -> icon file id (numbers only, committed, the one JSON the exe check allows in `web/`). `scripts/fetch_icon_map.py` builds it from `/data/wow/media/item/{id}` with Jack's key (once, and after a patch adds items; it keeps old entries). `ui/icons.py` makes the URL, `Bridge.icons()` sends template + ids, `js/itemicon.js` (`itemIcon`, `withIcon`) draws `<img loading=lazy>` or a bordered fallback square. Users need no key; the collector never fetches icons.
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

## Repository: code public, data never in it

- https://github.com/Jacklog-dev/Coppertrail (public) holds the code: `coppertrail` (collector, pattern jobs, GUI) and `pi/`. The data repository is deleted; there are no workflows that collect data.
- **Never commit collected data**: no auction data in a commit, test fixture, log line or artifact. Fixtures are hand-made.
- Blizzard's terms: data copied from the API (listings, item details) is kept at most 30 days; that is the Pi's raw data database. Jack's reading: what Coppertrail concludes from it (hourly summaries, sales estimate) is our own and kept forever in "our" database. Blizzard is named as the source without suggesting endorsement (README and the GUI status strip). At most 36,000 requests per hour.
- **Local layout:** `private/` (gitignored) is a local folder with the handover and design package in `private/handover/` (index in its `README.md`); its GitHub repo is gone.

## Architecture (see HANDOVER sections 2, 8 and 8a)

- **Stack:** Python 3.12, Parquet queried with DuckDB, pywebview (WebView2) with plain HTML/CSS/JS and uPlot. No Qt.
- **Collector:** a platform-neutral CLI (Windows, Linux/Raspberry Pi, GitHub Actions); the scheduler is a thin wrapper around it. Hour files are write-once, so a rerun of the same snapshot writes nothing.
- **Pattern jobs:** plain functions that return data frames, kept out of widget code so they are testable and callable from a CLI. Each one reports how many days of data it rests on.
- **GUI:** reads the local data directory only through the DuckDB query layer. Its only network action is the explicit "Pull latest data" (`ui/pull.py`): download the newest `copied-data` artifact with `gh api` (repo resolved from the data folder's remote, the user's `gh` login) into a staging folder, `git pull --ff-only` main, then swap `window/`; a failed step changes nothing. The app also prunes `window/` to 30 days at start.

## Design rules (HANDOVER 8b, enforce in review)

- All colours, fonts and sizes come from `coppertrail/ui/tokens.py` (copied from `private/handover/ui/tokens.py`) and the generated `web/css/tokens.css`. CSS and JS must not hard-code colours or font names.
- Almendra is used only for h1 and card titles, always uppercase. Everything else is Caudex.
- One 1 px border per panel. No ornaments, shadows, gradients or textures.
- Copper means "selected or primary" only. Coin colours are for price values only.
- Rising and falling are never shown by colour alone: always ▲/▼ plus a sign, with a real minus sign (−).
- No look-alike game UI (character view, profession window, tooltip frames, filigree borders), no game fonts (Friz Quadrata) or logos, and no "Warcraft" in the name. Real item icons by URL are allowed (Jack, 2026-11-18); never bundle or commit the images.
- The mock-ups in `private/handover/mockups*/` are the visual source of truth. Their numbers are invented sample data.

## Limits

- Read-only use of the Blizzard API.
- Do not create accounts, repos, keys or secrets without Jack's say-so.
- No bot actions in the game and no real-money gold trading.
