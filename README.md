# Coppertrail

Auction house market analysis for WoW Forever. Coppertrail collects price
history into a local archive, looks for patterns and outliers (daily rhythm,
mispricings, supply shocks, processing spreads, inflation), and shows them in
a desktop app (pywebview with an HTML/CSS front end and uPlot charts).

**Status:** early. The collector works. The GUI window frame and filters work;
its views and the pattern jobs come next.

```bash
uv run python -m coppertrail.ui --data-dir path/to/your/private/data
```

## Collector

Needs [uv](https://docs.astral.sh/uv/) (Python 3.12).

```bash
uv sync
uv run python -m coppertrail.collector --data-dir path/to/your/private/data run
```

One run fetches the AHledger price table, builds a watchlist of bulk and
high-value goods, and stores 7 days of hourly prices per item, per-scan data
for the top 200 items, and market totals. It writes them as Parquet day files.
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
