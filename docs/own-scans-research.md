# Own scans: research spike (HANDOVER section 3, step 7)

Date: 2026-11-17. No code changed. Goal: find a licence-free source for price history that keeps working after `API_ARCHIVE_UNTIL` (2026-12-09), based on Jack's own in-game auction house scans.

## Short answer

- **AHledger addon:** not usable as an archive source. It is "All Rights Reserved", its local file is a hand-off for the sync app, and its name and format are still undocumented. It is also not installed on this PC.
- **Auction House DataBase (AHDB, `AuctionDB`, LGPL-3.0):** already supports WoW Forever and keeps a **per-scan price history** (timestamp, min, median, quantity per item) in plain Lua strings in its SavedVariables file. With one option on, it also keeps every single auction of the last N scans. It is the best candidate for the importer.
- **Own addon:** possible as a fallback. The Forever client has the retail auction API (`C_AuctionHouse.ReplicateItems`), one full scan per 15 minutes, about 85,000 auctions in about 10 s.

Recommendation: import AHDB's SavedVariables (details at the end).

## What is on this PC

- WoW Forever install: `D:\Games\World of Warcraft\_forever_\` (product `wowf`, client 1.60.1.70938 in `.build.info`). There are other flavours next to it (`_retail_`, `_classic_era_`, `_anniversary_`, `_classic_beta_`). A second, almost empty retail install sits in `C:\Program Files (x86)\World of Warcraft\`.
- `Interface\AddOns\` in `_forever_` is **empty** today. No scan addon is installed.
- SavedVariables paths (read only, nothing modified):
  - account-wide: `_forever_\WTF\Account\<ACCOUNT>\SavedVariables\<Addon>.lua`
  - per character: `_forever_\WTF\Account\<ACCOUNT>\93\<Char>-<Realm>\SavedVariables\<Addon>.lua` (`93` is the region/realm-list folder)
  - The client writes a `.lua.bak` beside each file (the previous version).
- `Blizzard_AuctionHouseUI.lua` holds `g_auctionHouseSortsBySearchContext`. That is the **retail-style auction house UI** (`C_AuctionHouse`), not the old classic `AuctionFrame` / `QueryAuctionItems(getAll)` API. This matches what AHDB's source says about Forever.
- The only third-party SavedVariables left is `BetterPlayerNames.lua` (account-wide), an addon that has since been removed. It shows that account-wide SavedVariables persist normally on this client.

## 1. AHledger addon

Sources: the CurseForge page `curseforge.com/wow/addons/ahledger` (v0.15.0, 2026-11-17, owner Notedlemon, flavours Forever and Classic, game versions 1.60.1 and 1.15.9). `ahledger.com/addon` answered 429 twice during this spike, so the HANDOVER section 3 summary of that page stands.

- Scans: `/ahl scan` or a scan button at the AH runs one full scan with "the same call Auctionator and TSM use" (that is `ReplicateItems`), and shows the 15-minute server cooldown. It may also scan automatically about every 15 minutes.
- Scan contents (per the page): item ids, quantities, prices, time left, plus realm, faction and region. No character or seller names.
- Storage: **Save and upload** (`/ahl upload`) writes the scan to disk for the sync app. The game writes saved data only at logout or `/reload`. HANDOVER calls it a "packed listing" in SavedVariables. The file name and format are not published. The page also says options, market and watchlist are mirrored into addon CVars, so the addon does not rely on SavedVariables for its settings.
- `/ahl status` shows the version, market, price age and **stored scans**. The page does not say how many scans are kept locally. Most likely it holds the pending scan(s) until the sync app uploads them, not a growing history.
- Data flows the other way too: the sync app writes AHledger price tables into the addon folder every 30 minutes. That data is AHledger's and falls under their terms, so it must not be imported.
- Licence: **All Rights Reserved**. We may read our own file. We must not copy or reimplement its packing code from its source.

Assessment: to learn the format, Jack would have to install the addon, scan, `/reload`, and let me read the file. Even then, the file is a transient buffer whose format can change with any release, and it may be emptied after each upload. That is not a stable archive, so I don't recommend building on it.

## 2. Other scan addons for Forever

| Addon | Forever | Licence | Local history |
|---|---|---|---|
| **Auction House DataBase (AHDB)**, `mooreatv/AuctionDB`, v2.7.1 (2026-11-09) | yes, "WoW Forever edition", `## Interface: 16001, 120105` | LGPL-3.0 (source on GitHub) | **yes**: per scan and per day, see below |
| Hammerprice (sidoh10) | yes (1.60.1, TBC Anniversary) | MIT | market value, lowest buyout, a 14-day *weighted* history per item; per-scan values not documented. Shares scans with its own network by default (can be turned off). |
| Forever Ledger | Forever | ? | a gold ledger (`ForeverLedger.lua`), not AH prices |
| Auctionator / TSM | not checked for Forever | | Auctionator keeps per-day min prices only; TSM needs its desktop app |

### AHDB storage (read from its public source, LGPL; described, not copied)

- File: `WTF\Account\<ACCOUNT>\SavedVariables\AuctionDB.lua`, global `AuctionDBForeverSaved` (account-wide, so every character's scans land in one file).
- `AuctionDBForeverSaved.houses["<region>-forever-<ruleset> <House>"]`. For Jack that is probably `"eu-forever-normal Alliance"` (and `Horde`, `Neutral`). Forever rulesets are separate worlds with their own houses.
- Per house, two string-encoded maps keyed by item id:
  - `items[itemID]`: recent scans, `"ts,min,median,qty ts,min,median,qty ..."`, oldest first. `ts` is Unix server time; `min` is the lowest unit buyout; `median` is the **quantity-weighted median unit buyout**; `qty` is the units listed. Min/median are 0 when only bids existed. Kept for the house's last 30 scans, at most 7 days.
  - `daily[itemID]`: older days rolled up, `"ts,min,median,qty,scans ..."`. `ts` is the day's last scan, then the lowest min, the median of the scans' medians, the average quantity and the number of scans. Kept 180 days. Days are UTC.
  - Numbers are printed with `%.0f`, because prices can exceed 32 bits.
- Optional **Record full scans** (`recordScans`, `/ahdb keepscans N`, default 3): `saved.ah` is a list of scans `{realm, faction, char, ts, count, ..., data}`. `data` lists every auction as `itemKey!/timeLeft,count,minBid,buyout,curBid&...`. Seller names are empty on Forever. `saved.itemDB_2` maps item keys to item links (the format of AHDBapp).
- History is dropped for anything before 2026-11-01 (the Forever stress test).
- The 15-minute rule is kept in a CVar (`ahdbLastScan`). It survives `/reload` and logging into another character, but not a client restart.

Consequence: with AHDB, at least one scan every 2 to 3 days keeps its per-scan points before they get rolled up. Rolled-up days still hold one daily point per item for 180 days. Raising `RECENT_SCANS`/`RECENT_DAYS` is not an option (Jack would have to edit the addon). The importer simply runs often enough.

## 3. Forever client auction API (for an own addon)

From AHDB's source and its probe notes for Forever, plus the AH UI SavedVariables above:

- `C_AuctionHouse.ReplicateItems()` gives a **full snapshot of every auction** (about 85K entries on Forever), with data after about 10 s. Then `REPLICATE_ITEM_LIST_UPDATE` fires, `GetNumReplicateItems()` gives the count (indexes 0..n-1), and `GetReplicateItemInfo(i)` returns count, minBid, minIncrement, buyout, bidAmount, owner (only for your own auctions) and itemID. `GetReplicateItemTimeLeft(i)` and `GetReplicateItemLink(i)` are also there. `hasAllInfo` may stay false, but itemID, count and buyout are always present.
- **Cooldown:** one full scan per 15 minutes per client session. A request sent too early is **silently ignored**, so a scan addon needs a timeout. A request that returns nothing apparently doesn't count.
- The AH window must be open (an auctioneer NPC). Trial accounts can't use the AH.
- Targeted searches (`SendSearchQuery`, commodity/item search results) are throttled separately (`AUCTION_HOUSE_THROTTLED_MESSAGE_SENT`). They sometimes don't go out and need a resend.
- SavedVariables are written only at logout, `/reload` or client exit. A crash loses the session's scans.
- No automation: a scan has to start from Jack's interaction (opening the AH, a button). HANDOVER section 10 forbids bot actions anyway.

An own addon would be about 150 to 250 lines of Lua: ReplicateItems on AH open with a cooldown, then aggregation per item into `min, p25, median, p75, quantity, auctions` (unit buyout, weighted by count), and one line per item per scan in a string table. That would give Coppertrail all six columns, which AHDB does not (see 4). The cost is writing and maintaining it, against AHDB, which already works.

## 4. Importer sketch

A new module `coppertrail/ownscan/` (collector side, no GUI imports) with the command `python -m coppertrail.ownscan import [--sv PATH] [--house "eu-forever-normal Alliance"]`:

1. Find `AuctionDB.lua` under `<wow>\_forever_\WTF\Account\*\SavedVariables\`. The WoW path goes into `collector.toml` as `wow_dir`.
2. Parse it with a small read-only Lua-table parser in Python. The file only has nested `{}` tables with `["key"] = value` and `[n] = value` entries, strings and numbers, so no Lua runtime is needed. A library like `slpp` would also work, but a 60-line tokenizer is safer. Read a copy, never the live file while WoW is running.
3. Select the house that matches `forever.normal.alliance.eu`.
4. Map the data:

| AHDB | Coppertrail table | Columns |
|---|---|---|
| `items[id]` point `ts,min,median,qty` | `scans` | `item_id=id`, `observed_at=ts` (UTC), `min`, `median`, `quantity=qty`, `p25=p75=auctions=NULL`, `source='own_scan'`, `run_id='ownscan-<file mtime>'` |
| the same points, grouped by UTC hour | `hourly` | `hour=floor(ts)`; with one scan in the hour, its values; with several, min of min, median of medians, last quantity; `p25/p75/auctions` NULL; `source='own_scan'` |
| `daily[id]` `ts,min,median,qty,scans` | new table `daily_own` (or `hourly` at 12:00, flagged) | only for days with no per-scan points left |
| optional `saved.ah` full scans | `scans` + `hourly` with **all** columns | p25/p75/median weighted by count, `auctions` = number of listings, `quantity` = sum of counts |

5. Upsert through the existing store (`store.py` keys `hourly(item_id, hour)` and `scans(item_id, observed_at)`), so reimports are idempotent. **Conflict with API rows:** the key does not include `source`, so an own scan in the same hour would overwrite an API row (or the reverse). Decide one of two: own scans only fill hours that have no API row (simplest, and nothing overlaps after the cutoff anyway), or `source` joins the key. I recommend the first: up to 2026-12-09 the API wins, after that only own scans exist.
6. `items` (name, class, quality) stay as they are. New item ids from scans get their master data from the AHDB item links when recording is on, otherwise they stay without a name until a tooltip run (allowed on demand, not archived).

What is lost compared with the API:

- **Coverage:** one player's scans, only when Jack is online at an auctioneer, at most every 15 minutes. The API merges several players per hour. Expect big gaps (nights, days off). The patterns' `min_days`/basis line must count *days with own scans*, not calendar days.
- **Columns:** with AHDB's summary only `min`, `median`, `quantity`. No `p25`, `p75` or `auctions` (no spread for patterns that use the interquartile range). With **Record full scans** on, all of them, but only for the last N scans per file write (default 3), so it needs an import after each session.
- **Snapshot fields:** `sales_per_day`, `median_7d/30d`, `low/high_30d` come from AHledger's model. Coppertrail could compute rolling medians itself. Sales per day can only be estimated, from auctions disappearing between consecutive full scans, which is noisy (cancels, expiries).
- **Economy:** gold listed and auction count per day can be computed from full scans (sum of buyouts, count), but only on recorded scans.
- **Median definition:** AHDB's median is quantity-weighted over buyouts. AHledger's may differ (its method is not published). Don't splice the two series without a visible source switch in charts.
- **Timeliness:** the data reaches disk only at logout or `/reload`.

## Recommendation for Jack

**Feasible: yes, via AHDB. Effort: about 1 to 2 days** (Lua-table parser with tests, mapping, upsert rule, a CLI command, and a status line in the GUI).

What Jack does in game:

1. Install **Auction House DataBase (AHDB)** for WoW Forever (CurseForge project 336518, or the GitHub releases of `mooreatv/AuctionDB`). It is the only addon here; you install it, not Claude.
2. In its options, turn on **Record full scans** (for p25/p75/auction counts), and if it helps, `/ahdb keepscans 10`. Watch the file size: about 85K auctions per scan is probably several MB per kept scan (estimate, not measured).
3. Open the auction house when it suits you (once per 15 minutes counts). Holding Shift skips a scan. Do a `/reload` or log out before closing the game, so the file gets written.
4. Run `python -m coppertrail.ownscan import` at least every 2 to 3 days (later perhaps automatically when the GUI starts), so no per-scan points get rolled up.
5. Then send me one real `AuctionDB.lua` (or let me read it in place). The format above comes from the source, and a real file confirms it before the parser is written.

Not recommended: the AHledger addon file (closed licence, transient, undocumented). An own scan addon only makes sense if AHDB stops working or its file grows too large. It is the fallback, and it would give all six columns.

Open points:

- Whether a `/reload` with several MB of recorded scans makes the client stutter, to be tested by Jack.
- Whether Jack's account also scans the Horde/Neutral houses. The importer should take only `Alliance` for this market.
- AHDB has a sharing feature (Comm.lua): "trusted characters" can merge points. Merged points from other players are still not AHledger data, but they are not purely Jack's own scans either. Keep `source='own_scan'` only if sharing stays off, or mark merged points.
