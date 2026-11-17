# Changelog

## 0.0.1 [Core]

- Collector: throttled AHledger CLI writing Parquet day files, resumable runs, gap report, archive cutoff 2026-12-09
- Collector: item subclass, vendor price and required level; recipes and game builds tables
- Daily collection in GitHub Actions (private data repo)
- GUI on pywebview + HTML/CSS/JS with uPlot charts (no Qt)
- GUI: theme, window frame, nav rail, status strip with AHledger credit
- GUI: filter bar (groups, class, search, date range, min sales) and item-group editor
- GUI: empty, stale, no-match, loading, pull-failed and too-little-history states; compact and ultrawide layouts; chart building blocks
- Query layer for hourly, per-scan, snapshot, economy and item data
- Pattern CLI and baseline check against the handover results
- Research note on importing own in-game scans
- Pattern jobs (all 12): daily rhythm, weekday and raid reset, mispricings, supply shocks, buyouts, mean reversion, processing spreads, progression wave, correlated items, vendor floor, build effects, inflation index
- Patterns that lack history show when they will be ready
- GUI: Market overview and Item detail views on real data
- Windows build: single `Coppertrail.exe` (PyInstaller), no data bundled; workflow attaches it to tagged releases
