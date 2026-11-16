# Coppertrail

Auction house market analysis for WoW Forever. Coppertrail collects price
history into a local archive, looks for patterns and outliers (daily rhythm,
mispricings, supply shocks, processing spreads, inflation), and shows them in
a desktop app built with PySide6 and pyqtgraph.

**Status:** early. Code follows.

## Data

Prices from [AHledger](https://ahledger.com).

This repository ships **no market data**. The collector builds the archive
locally (or in your own private repository), and it is never published here.

## Not affiliated

Coppertrail is a fan-made tool. It is not affiliated with or endorsed by
Blizzard Entertainment and contains no game assets.

## License

[MIT](LICENSE). The fonts it uses (Caudex, Almendra) are under the SIL Open Font License.
