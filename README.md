# Coppertrail

Auction house market analysis for WoW Forever. Coppertrail collects price
history into a local archive, looks for patterns and outliers (daily rhythm,
mispricings, supply shocks, processing spreads, inflation), and shows them in
a desktop app (pywebview with an HTML/CSS front end and uPlot charts).

**Status:** all four views and all twelve pattern jobs work. Patterns that need
more history than the archive holds say how many days are missing and when they
will be ready.

```bash
uv sync
uv run python -m coppertrail.ui --data-dir path/to/your/private/data
```

## What it shows

- **Market overview:** price index of farmable against scarce goods, daily
  rhythm, total listed supply and gold, and what changed in the last 7 days.
- **Item detail:** lowest buyout and lower quartile over time with listed
  quantity, vendor floor and events, plus the hour-of-day profile.
- **Patterns:** one tab per pattern, each stating how many days of data it rests
  on: daily rhythm, weekday and raid reset, mispricings, supply shocks, buyouts,
  mean reversion, processing spreads, progression wave, correlated items, vendor
  floor, patch and build effects, inflation.
- **Movers & outliers:** biggest risers and fallers, current mispricings.
- Filters for item groups (editable), class, name, date range and minimum sales
  per day apply to every view and are remembered.

The only network action in the app is "Pull latest data", which runs `git pull`
on your data folder.

### Pattern jobs from the command line

```bash
uv run python -m coppertrail.patterns list
uv run python -m coppertrail.patterns run daily_rhythm --group "Leather chain"
```

### Windows executable

```bash
uv sync
uv run python scripts/build_exe.py
```

This builds a single `dist/Coppertrail.exe` (about 80 MB) with PyInstaller. It
contains the app and its web front end, no market data. On first start, choose
your data folder in the app (or put the data clone in a `private` folder next to
the exe). Edge WebView2 must be installed; Windows 11 ships it.

## Collector

Needs [uv](https://docs.astral.sh/uv/) (Python 3.12).

```bash
uv sync
uv run python -m coppertrail.collector --data-dir path/to/your/private/data run
```

One run fetches the AHledger price table, builds a watchlist of bulk and
high-value goods, and stores 7 days of hourly prices per item, per-scan data
for the top 200 items, market totals, recipes, game builds and item details
(subclass, vendor price). It writes them as Parquet day files.
The collector uses the keyless rate (30 requests per minute), so a run takes
about 40 minutes. It is safe to rerun, and an interrupted run resumes where it
stopped. Archiving from the API stops at a configurable cutoff
(`api_archive_until`), because AHledger's terms change on 10 December 2026.

## Data

Prices from [AHledger](https://ahledger.com).

This repository ships **no market data**. The collector builds the archive
locally (or in your own private repository), and it is never published here.

## Not affiliated

Coppertrail is a fan-made tool. It is not affiliated with or endorsed by
Blizzard Entertainment and contains no game assets.

## License

[MIT](LICENSE). The fonts it uses (Caudex, Almendra) are under the SIL Open Font License.
The bundled chart library [uPlot](https://github.com/leeoniya/uPlot) is MIT licensed.
