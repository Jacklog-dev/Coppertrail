# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

No code yet. The public repo holds only docs so far. **`private/handover/HANDOVER.md` is the spec. Read it before you start any work.** Section 8b is the visual design, and section 9 is the order of work. Once the toolchain exists, add the build, lint and test commands here.

Coppertrail is a local auction house analysis tool for WoW Forever (market `forever.normal.alliance.eu`). It collects price history from the AHledger API into a private Parquet archive, runs pattern jobs over it, and shows the results in a desktop GUI. Code, comments and conversation are in English.

## Repositories: code public, data private

| Repo | Visibility | Holds |
|---|---|---|
| https://github.com/Jacklog-dev/Coppertrail | public | Python package `coppertrail` (collector, pattern jobs, GUI) |
| https://github.com/Jacklog-dev/Coppertrail_Data | private | Scheduled GitHub Actions workflow plus the Parquet day files |

- **Never commit collected data to the public repo.** Doing so would redistribute AHledger data, which their terms forbid. Put the data directory in `.gitignore` from the first commit.
- The README must credit "Prices from AHledger" with a link and state that the repo ships no data. The GUI status strip shows the same credit at all times.
- The private repo's workflow checks out the public code, runs the collector once a day (about 40 min, with `timeout-minutes` set) and commits the new day files to itself.
- The handover and design package live in `private/handover/` (index in its `README.md`). That folder is gitignored and must never be pushed to the public repo; its home is the private data repo.

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

- Price table columns 5 to 8.
- The fields of a `range=24h` point.
- Whether `/api/catalog` provides subclasses.
- Whether Caudex has tabular figures.
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
