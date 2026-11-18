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

The only network action in the app is "Pull latest data". It downloads the latest
copied item data (with the [GitHub CLI](https://cli.github.com/), signed in with
`gh auth login`) into the `window/` folder and fast-forwards your data folder
(`git pull --ff-only`). How the pieces fit together: [docs/architecture.md](docs/architecture.md).

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
uv run python -m coppertrail.collector --data-dir path/to/your/private/data hourly
uv run python -m coppertrail.collector --data-dir path/to/your/private/data nightly
```

The collector reads the auction house from the Blizzard Game Data API. It needs
your own API client: set `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET`, or put
`client_id` and `client_secret` in a `[blizzard]` table in `blizzard.toml` in the
Coppertrail settings folder (`%APPDATA%\Coppertrail`, or `~/.config/coppertrail`).

- `hourly` fetches the latest snapshot and writes one file of hourly conclusions
  per snapshot (prices per item, listed quantity, estimated sales). It is safe to
  rerun: an hour that is already stored is never written twice.
- `nightly` rebuilds the item selection and refreshes item details and recipes.
- Both prune the copied data in `window/`, so nothing in it is older than 30 days.

## Data and privacy

- Market data comes from the Blizzard Entertainment Game Data API and is
  provided "as is", without any warranty of accuracy or completeness.
- Coppertrail is a fan-made tool. It is not affiliated with or endorsed by
  Blizzard Entertainment and contains no game assets.
- This repository ships **no data**. The collector builds the archive in your own
  data folder (or your own private repository), and it is never published here.
- Data copied unchanged from Blizzard (current listings, item details, recipes) is
  kept for at most 30 days. Coppertrail's own hourly conclusions drawn from it
  (prices, quantities, sales estimates per item and hour) are kept longer.
- Nothing is collected about users: no accounts, no telemetry, no tracking. The app
  makes no network request except "Pull latest data", and only when you click it.
- The copied data is never stored in git. It moves between collector runs as a
  short-lived GitHub Actions artifact that GitHub deletes after a day, and the
  app deletes local copies older than 30 days at every start and pull.

## License

[MIT](LICENSE). The fonts it uses (Caudex, Almendra) are under the SIL Open Font License.
The bundled chart library [uPlot](https://github.com/leeoniya/uPlot) is MIT licensed.
