# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

The collector exists (HANDOVER section 9, steps 1 to 3). The GUI theme module and style sample exist (step 6.1, awaiting Jack's review); there are no pattern jobs or views yet. **`private/handover/HANDOVER.md` is the spec. Read it before you start any work.** Section 8b is the visual design, and section 9 is the order of work.

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
uv run python -m coppertrail.ui.sample                # GUI style sample window (--light, --screenshot PNG)
```

Collector notes:
- The data dir defaults to `$COPPERTRAIL_DATA`, or `./private` if that is unset. Optional overrides go in `<data-dir>/collector.toml` under a `[collector]` table, with the field names from `coppertrail/collector/config.py`.
- Exit codes: 0 ok or partial, 1 failed, 2 another run holds the lock, 3 the `API_ARCHIVE_UNTIL` cutoff was reached or archiving is disabled.
- Each fetched item is staged in `<data-dir>/.staging/<run_id>/` and merged into the day files at the end of the run. Rerunning after a crash resumes the run, as long as it started within the last 12 h.
- Day-file tables: `hourly`, `scans`, `snapshot`, `economy`, `items`, `watchlist`, `runs`, `gaps`, `population`. Logs go to `<data-dir>/logs/`.

GUI notes:
- PySide6 (`pyside6-essentials`) and pyqtgraph sit in the `gui` extra, pulled in by the dev group. The collector workflow runs `uv sync --no-dev`, so it does not install them.
- `coppertrail/ui/`: `tokens.py` (design tokens), `theme.qss` (template filled with `str.format_map`), `theme.py` (fonts, `font(role)`, `color(token)`, `icon(name)`, `apply_theme`), `format.py` (coins, signed percent, dates; no Qt), `widgets.py` (Card, CoinLabel/CoinDelegate, ChangeDelegate, Dot, legend), `charts.py` (pyqtgraph styling).
- QSS must not set `font-family`/`font-size` or `background` on plain `QWidget`: the first beats `setFont` (which breaks Almendra and the type scale), the second paints every layout container.
- Caudex Regular has equal-width digits; Caudex Bold does not (narrow "1"), so keep numeric columns at weight 400. Caudex lacks ▲ ▼ ●: dots are painted (`Dot`), arrows come from the system fallback font (Segoe UI Symbol on Windows).

## Verified API facts (2026-11-16)

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

- **Stack:** Python 3.12, Parquet queried with DuckDB, PySide6 (Qt Widgets) with pyqtgraph.
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

- All colours, fonts and sizes come from `coppertrail/ui/tokens.py` (copied from `private/handover/ui/tokens.py`) and the QSS template. Widget code must not hard-code colours or font names.
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
