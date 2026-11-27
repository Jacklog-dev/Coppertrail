# AGENTS.md

This file provides guidance to Codex (claude.ai/code) when working with code in this repository.

Coppertrail is a local auction house tool for WoW Forever (Normal Alliance EU). Code, comments and conversation are in English.

## Status: starting over

**Since 2026-11-24 the app starts over on one data source: the raw data database on the Raspberry Pi.** Nothing collected before it matters, and existing code is material to reuse, refactor or delete as the new work needs; do not ask what happens to old code or old features.

- Two separate databases, never linked: the Pi's raw data database (Blizzard's data as sent, 30 days) and "our" database on the PC (our own results, kept forever). Both use **SQLite** (Jack: one technology for both). The PC only gets what the Pi's `export` hands out.
- **First step, and the only scope for now:** our database on the PC, a listings overview (every listed item with its current lowest price) and an item detail (its lowest price and an hourly chart of it). Only the lowest price matters. Item names come with the item details in the export; the PC keeps the latest copy.
- Built (2026-11-25): `coppertrail/db.py` (our database, `%APPDATA%\Coppertrail\coppertrail.sqlite`: `price(item_id, at, low)` per hour, `hour`, `name`, `bookmark`), `coppertrail/sync.py` (SSH export -> lowest price per item and hour, names; `$COPPERTRAIL_PI` overrides the host), and one GUI screen: item list with search and sort, item detail with price, change and an hourly chart (`ui/bridge.py`, `web/js/main.js`, `web/js/chart.js`, `web/css/app.css`).
- Work one small step at a time. Ask Jack only what changes the current step.
- Branches: session branches merge into `dev`; `main` is a release (major version bump, exe, GitHub tag) and only on Jack's call.

## Raspberry Pi (raw data database, the only source)

- **Access:** `ssh coppertrail@coppertrail-pi` (key login, passwordless sudo). Raspberry Pi 1 B+: armv6l, 426 MB RAM, 29 GB SD card, Raspberry Pi OS Lite 32-bit (Trixie), Python 3.13, SQLite 3.46. Code that runs on the Pi uses the standard library only (no armv6 builds of DuckDB, pyarrow, pandas). Keep the Pi's work minimal: it stores and hands out bytes, it never summarises.
- **Database:** one file, `/var/lib/coppertrail/raw.sqlite` (WAL). `snapshot`: one row per listing response (`items`|`commodities`, hourly), the body exactly as received (gzip), 3–4 MB per hour. `item`: one row per item lookup (200 body as received, or a 404 row). `id`/`seq` only grow and are the PC's bookmarks.
- **Jobs:** `coppertrail-raw.timer` at :27 UTC runs `coppertrail_raw.py collect` (deletes rows that would turn 30 days old, then stores new responses; `If-Modified-Since`, retries every 5 min until :55). `coppertrail-items.timer` at :00 runs `items` (item details missing, older than 25 days, or a 404 older than 7 days; stops at :20). Same lock; exit codes 0/1/2. Logs: `journalctl -u coppertrail-raw.service` / `-u coppertrail-items.service`.
- **Export:** `ssh coppertrail@coppertrail-pi "python3 /opt/coppertrail/coppertrail_raw.py export --after-snapshot ID --after-item SEQ"` streams every newer row (JSON header line + body bytes, then an end line). Read-only, no credentials. Format in `pi/README.md`.
- **30-day limit:** if the Pi is off nothing is deleted, which Jack accepts (an off Pi is broken, or the project has ended).
- **Credentials:** `/etc/coppertrail/blizzard.env` (root:coppertrail, 640), set with `sudo bash /opt/coppertrail/set-blizzard-secret.sh` (hidden input, then a token check). Never print or copy that file, and never log, print or commit credentials or tokens.
- **Code:** `pi/` (script, units, `install.sh`, `set-blizzard-secret.sh`), tests `tests/test_pi_*.py`. Deploy: copy `pi/` to the Pi, then `sudo bash install.sh` outside :25–:56 and :00–:20 (`--status` shows both timers, the last log lines and the database size). Spec `docs/superpowers/specs/2026-11-24-pi-raw-store-design.md`.
- The raw data lives on the Pi only. Never copy it into this repo (an export for a test goes to a scratch folder and is deleted afterwards).

## Blizzard data facts

- Prices are copper per unit (int64): commodities `unit_price`, items `buyout / quantity`. Bid-only listings have no price.
- House 111 under ruleset 2 is Normal Alliance EU. Snapshots update once an hour at about :23 UTC.
- About 240 listed items are unknown to Blizzard (stored as 404 rows); show them by item id.

## Commands

The toolchain is [uv](https://docs.astral.sh/uv/) with Python 3.12 (pinned in `.python-version`).

```bash
uv sync                                   # create .venv, install deps and dev tools
uv run pytest -q                          # tests (offline, mocked HTTP)
uv run ruff check .                       # lint
uv run ruff format .                      # format
uv run python -m coppertrail.sync                     # sync our database from the Pi once
uv run python -m coppertrail.ui                       # the GUI window (syncs at start; --no-sync, --db FILE)
uv run python -m coppertrail.ui --dev --port 8765     # serve the page on 127.0.0.1 for a normal browser
uv run python -m coppertrail.ui --screenshot shot.png # headless Edge screenshot (--item ID opens a detail)
uv run python -m coppertrail.ui.webtheme              # regenerate web/css/tokens.css after editing tokens.py
uv run python scripts/build_exe.py                    # Windows build: dist/Coppertrail.exe
```

## Changelog

Every push to `main` adds its changes to `CHANGELOG.md`: short bullet points only, no prose, no dates. Bullets go under the current version heading (`## 0.0.1 [Core]`); start a new version heading only when Jack names one.

## GUI rules

- No Qt, ever (Jack's rule): a test fails if PySide/PyQt/qtpy/pyqtgraph appear in `uv.lock` or as imports. pywebview backends: EdgeChromium (WebView2) on Windows, GTK on Linux, Cocoa on macOS; never `gui="qt"`.
- Front end in `coppertrail/ui/web/`: plain HTML/CSS/ES modules, no build step, no Node. `js/api.js` is the only way to Python (pywebview `js_api` in the app, `POST /api/<name>` on the dev server); `bridge.py` returns JSON-able dicts and `Bridge.EXPOSED` lists what JS may call.
- JS writes data strings with `textContent` (the `el()` helper in `js/dom.js`), never `innerHTML`. Display strings come from Python (`format.py`); JS only formats chart axes and chart dates (en-GB, Europe/Berlin).
- Pages load nothing remote (fonts via `@font-face`, uPlot vendored in `web/vendor/`, CSP meta in every page). The one exception: item icon images from `https://render.worldofwarcraft.com` (CSP `img-src` only; the host lives in Python). `web/icon-map.json` maps item id -> icon file id (numbers only); never bundle or commit icon images.
- The exe bundles `coppertrail/ui/web/` only, never data files.
- User settings live in `%APPDATA%\Coppertrail` (or `~/.config/coppertrail`); `$COPPERTRAIL_CONFIG` overrides the folder, and tests and manual `--dev` sessions should set it.

## Design rules (HANDOVER 8b, enforce in review)

- `private/handover/` (local, gitignored) holds the visual design: HANDOVER section 8b and the mock-ups in `mockups*/` are the visual source of truth. Their numbers are invented sample data.
- All colours, fonts and sizes come from `coppertrail/ui/tokens.py` and the generated, committed `web/css/tokens.css` (`test_webtheme.py` fails when it is stale). CSS and JS must not hard-code colours or font names.
- Almendra is used only for h1 and card titles, always uppercase. Everything else is Caudex. Caudex Bold has a narrow "1", so numeric columns stay at weight 400.
- One 1 px border per panel. No ornaments, shadows, gradients or textures.
- Copper means "selected or primary" only. Coin colours are for price values only.
- Rising and falling are never shown by colour alone: always ▲/▼ plus a sign, with a real minus sign (−).
- No look-alike game UI (character view, profession window, tooltip frames, filigree borders), no game fonts (Friz Quadrata) or logos, and no "Warcraft" in the name.

## Repository: code public, data never in it

- https://github.com/Jacklog-dev/Coppertrail (public) holds the code only.
- **Never commit collected data**: no auction data in a commit, test fixture, log line or artifact. Fixtures are hand-made.
- Blizzard's terms: data copied from the API (listings, item details) is kept at most 30 days; that is the Pi's raw data database (and the PC's latest copy of item details). Jack's reading: what Coppertrail concludes from it (prices per item and hour) is our own and kept forever. Blizzard is named as the source without suggesting endorsement. At most 36,000 requests per hour.

## Limits

- Read-only use of the Blizzard API.
- Do not create accounts, repos, keys or secrets without Jack's say-so.
- No bot actions in the game and no real-money gold trading.
