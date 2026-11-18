# Changelog

## 0.0.1 [Core]

- Collector on Blizzard's Game Data API: hourly run (house 111, Normal Alliance EU) and nightly run, platform-neutral CLI
- Hourly per-item summaries (quantity-weighted quantiles, quantity, auctions) and a sales estimate from consecutive snapshots
- House totals per snapshot; item selection from config rules (quality, class, minimum median, cap by traded gold)
- Item details, recipes and game builds from Blizzard; copied data kept on a 30-day window branch
- Hourly and nightly collection in GitHub Actions (private data repo)
- GUI on pywebview + HTML/CSS/JS with uPlot charts (no Qt)
- GUI: theme, window frame, nav rail, status strip with the Blizzard data credit
- GUI: filter bar (groups, class, search, date range, min sales) and item-group editor
- GUI: empty, stale, no-match, loading, pull-failed and too-little-history states; compact and ultrawide layouts; chart building blocks
- GUI: Market overview, Item detail, Patterns and Movers & outliers views
- "Pull latest data" fast-forwards main and resets the window checkout
- Query layer for hourly, house, item, recipe and build data
- Pattern jobs (all 12): daily rhythm, weekday and raid reset, mispricings, supply shocks, buyouts, mean reversion, processing spreads, progression wave, correlated items, vendor floor, build effects, inflation index
- Patterns that lack history show when they will be ready
- Pattern CLI and baseline check
- Windows build: single `Coppertrail.exe` (PyInstaller), no data bundled; workflow attaches it to tagged releases
- README: data and privacy section
