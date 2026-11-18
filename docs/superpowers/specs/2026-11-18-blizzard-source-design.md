# Blizzard as the only data source

Date: 2026-11-18. Status: design, waiting for Jack's approval.

## Intent

Coppertrail switches its data source to Blizzard's official Game Data API and removes the old third-party source completely: its code, its data and every mention of it. A test searches the tree for leftovers. This is Jack's decision. His reasons: the official API is the better source, the old source never answered, and he wants no affiliation with it. Losing the history collected since 2026-11-12 is fine with him; the game has been live for two weeks.

## Goals

- An hourly collector that reads auction house 111 (ruleset 2 "Normal", Alliance, EU) from the Blizzard API. It runs in GitHub Actions in the private data repo and stores per-item hourly summaries for a configurable item selection (at most 2,000 items).
- Our own sales estimate from listings that disappear between two snapshots.
- Item details, recipes and the game build, also from Blizzard.
- Our concluded data (hourly per-item summaries and the sales estimate from comparing two snapshots) is kept for the long term, so it can span whole patch cycles. Data copied unchanged from Blizzard (listings, item details, recipes, build names) is kept for at most 30 days.
- The item filter lives in a config file, so it can change later without code changes.
- One collector command that runs the same on Windows, Linux (Raspberry Pi) and in GitHub Actions.
- The patterns and the GUI work on the new tables.
- Afterwards: no trace of the old source left in either repository (including git history), in the GitHub data repo, or in the project folder on this PC.

## Non-goals

- Archiving single listings (about 50 MB a day). This could come later on Jack's Raspberry Pi, outside git.
- Other houses, factions, rulesets or regions. The config holds the ids, so a second house is possible later, but it is not built now.
- Character, guild or profile endpoints.
- Running the collector on the Raspberry Pi now. The command has to be able to; setting up the Pi is Jack's job, later.

## Anti-goals (a failure even if it works)

- Any auction data in the public repo: in a commit, a test fixture, a log line or an Actions artifact.
- Data copied unchanged from Blizzard (listings, item details, recipes, build names) older than 30 days anywhere in the data repo, its git history or the Actions cache.
- The client secret in either repo, in a log or in an error message.
- Equipment flooding the selection (Jack excludes it on purpose, except epic).
- Qt anywhere (unchanged project rule).

## Constraints

### Blizzard Developer API Terms of Use (last updated 2019-10-01)

- "You must implement a maximum 30-day TTL (time-to-live) policy for all Data obtained through our APIs."
- Blizzard must be "clearly and conspicuously" named as the source of the data, without suggesting endorsement or affiliation. No Blizzard trademarks in the app's title or URL.
- A privacy policy is required, stating that the data is provided "as is".
- At most 36,000 requests per hour. The key is confidential. No for-pay "premium" features, no handing data to third parties.
- **Jack's reading (his decision, 2026-11-18):** the 30-day limit applies to data copied unchanged from the API: listings, item details, recipes and build names. What Coppertrail concludes from it is his data and is kept for the long term. That covers the hourly per-item summaries (quantiles, quantity, counts) and the sales estimate, which only exists by comparing two snapshots. The terms do not address processed or derived data. If Blizzard ever says otherwise, `summary_retention_days` in the config (see below) must be able to delete older summaries.

### Verified API facts (probes on 2026-11-18)

- Token: `POST https://oauth.battle.net/token`, `grant_type=client_credentials`, HTTP basic auth with client id and secret. Requests go to `https://eu.api.blizzard.com` with `Authorization: Bearer`, `namespace=dynamic-forever-eu` or `static-forever-eu`, and `locale=en_GB`.
- Rulesets: `/data/wow/ruleset/index`, where 2 = Normal. Houses: `/data/wow/ruleset/2/auctions/` (the trailing slash is required). There are 5 Alliance houses: 110, 111, 112 (empty), 119 and 123. **111 is Normal Alliance EU**: its medians matched the old source exactly. The houses share no auction ids.
- Listings: `/data/wow/ruleset/2/auctions/111` (items: `id, item{id,...}, quantity, buyout, bid, time_left`, about 116,000 listings, 10 MB) and `.../111/commodities` (`id, item{id}, quantity, unit_price, time_left`, about 96,000 listings, 8.5 MB). 14 listings had a bid only.
- `time_left` is SHORT, MEDIUM, LONG or VERY_LONG.
- **Update rhythm:** once an hour at about :22:5x UTC. `Last-Modified` is set, `If-Modified-Since` returns 304, and `cache-control` is `max-age=86400`.
- One hour (11:22 to 12:22 UTC):
  - 36,021 listings gone, including all 5,662 SHORT ones.
  - 49,082 new.
  - 368 commodity listings shrank (13,263 units partly bought).
  - Auction ids are stable across snapshots.
- Item details: `/data/wow/item/{id}` in `static-forever` gives `name, quality.type, item_class.name/id, item_subclass.name/id, required_level, sell_price, purchase_price, level`. 2,953 of 6,848 listed items return 404 there. 2,768 of those are found in `static-classic1x`. 185 are found nowhere (mostly new Forever items). Item lookups at 10 parallel requests hit 429 after about 4,000 calls; at 4 parallel requests with backoff they went through.
- Recipes: `/data/wow/profession/index` (12 professions plus a "Test Profession [DNT]"), then `/profession/{id}` → `skill_tiers`, then `/profession/{id}/skill-tier/{tier}` → `categories[].recipes[]`, then `/recipe/{id}` → `crafted_item{id}`, `reagents[]{reagent{id}, quantity}` and `crafted_quantity.value`. In the probe, Tailoring had 17 categories.
- Build: the namespace header reads `static-1.60.1_70399-forever-eu`, so version and build come from it.
- Token price: `/data/wow/token/index` is 404 for Forever (not needed).

### Project and hosting

- GitHub Actions in the private data repo (Jack's decision, 2026-11-18). Never the public repo: logs and artifacts there are public.
- Minutes: a private repo on the free plan has 2,000 minutes a month (Jack's figure, not re-verified). Hourly runs of about 2 minutes plus one nightly job come to about 1,500 minutes a month.
- The selected items fit the size budget: 1,642 items today, a 34 KB hour file, about 0.8 MB a day.
- The collector is platform-neutral Python (pathlib, no Windows-only calls). Credentials come from `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET`, otherwise from `blizzard.toml` in the Coppertrail config folder.

## Approaches considered

| | What | Trade-off | Decision |
|---|---|---|---|
| A | Hourly per-item summaries, written as hour or day files, previous listings in the Actions cache | small, simple, enough detail for the patterns | **chosen** |
| B | Like A, but committed once a day from the cache | fewer commits, but a cleared cache loses a whole day | rejected |
| C | Archive every listing | full detail, about 50 MB a day, too big for git | later, Pi only, not in scope |

Storage under the 30-day rule: git keeps deleted files in history. The copied Blizzard data therefore lives on a small branch that is rebuilt daily (below), and the concluded data lives on `main` with ordinary history. Alternatives were:
- Actions artifacts with a 30-day retention. They expire on their own, but the GUI would need a GitHub token and many downloads.
- A single rewritten branch for everything. The GUI would always have to reset instead of pull.

Neither fits as well.

## The design

### Item selection (config, Jack's rule)

`collector.toml` in the data repo, table `[selection]`:

```toml
[selection]
exclude_qualities = ["POOR"]            # no grey items
min_median = { COMMON = 50 }            # white items need a median of at least 50 copper
exclude_classes = ["Recipe"]
equipment_classes = ["Armor", "Weapon"]
equipment_min_quality = "EPIC"          # equipment only at epic quality or better
include_unclassified = true             # items Blizzard does not know yet
max_items = 2000                        # safety cap, ranked by traded gold
rank_days = 7
keep_rank = 2200                        # an item already in stays while it ranks within this
```

- The quality order is POOR < COMMON < UNCOMMON < RARE < EPIC < LEGENDARY < ARTIFACT < HEIRLOOM.
- The class and quality rules come from item details and are static.
- `min_median` and the ranking need prices for every candidate, but only selected items are stored. The nightly job therefore works from the latest full listings in the Actions cache: it summarises all items in memory and applies `min_median` to that snapshot's median.
- Ranking (it only matters above `max_items`):
  - items with history rank by `sold_est × median` summed over the hourly rows of the last `rank_days`;
  - items without history rank by the estimate of the latest snapshot pair;
  - `keep_rank` keeps members from dropping out at the margin.
- The selection is rebuilt nightly and stored as `selection/<day>.parquet` on main (`item_id, reason, rank`; it is our own list). The hourly run uses the latest one, so membership changes once a day and series don't flicker. On the very first run, the hourly run computes one from the current snapshot.
- Unclassified items are looked up again daily.
- Today this gives 1,642 items (689 Consumable, 361 Trade Goods, 185 unclassified, 152 Quest, 122 Miscellaneous, 55 epic gear, 78 others), so the cap does nothing yet.

### Other config

```toml
[blizzard]
region = "eu"
ruleset = 2
house = 111
expect_house_name = "Alliance"   # a run fails if the house name no longer matches
locale = "en_GB"

[retention]
copied_days = 30                 # listings snapshot, item details, recipes, build names
summary_retention_days = 0       # 0 = keep hourly summaries and house rows for good (Jack's reading)
```

### Tables

Main branch (concluded data, kept, ordinary git history):

- `hourly/<UTC day>/<HH>.parquet`, one file per snapshot, written once and never rewritten, so git grows only by new data (about 34 KB per hour, 0.8 MB a day, roughly 290 MB a year): `item_id, hour (UTC, the snapshot's Last-Modified floored to the hour), observed_at (Last-Modified), min, p25, median, p75` (copper per unit, quantity-weighted; bid-only listings excluded from prices), `quantity, auctions, gone_units, partial_units, short_gone_units, new_units, span_hours, source='blizzard'`. Key `(item_id, hour)`.
- `house/<UTC day>/<HH>.parquet`: one row per snapshot for the whole house, unfiltered: `hour, observed_at, auctions, units, gold_listed` (sum of unit price × quantity), `gone_auctions, new_auctions, sold_value_est, source`.
- `selection/<day>.parquet` (above), `builds/<day>.parquet` (below), `collector.toml`, the workflows, and the scrubbed handover (`handover/`).
- Many small hour files are fine for DuckDB, because the query layer only reads the days in range. If the repo gets near 1 GB, a later change can merge old months into month files and squash main's history. Not part of this work.

Window branch (copied unchanged from a source, at most `copied_days`, one folder per source):

- `blizzard/items/<day>.parquet`: item details (`item_id, name, quality, class_id, class, subclass_id, subclass, required_level, sell_price, purchase_price, item_level, namespace, fetched_at`), the newest row per item wins.
- `blizzard/recipes/<day>.parquet`: `recipe_id, name, profession, crafted_item_id, crafted_qty, reagent_id, reagent_qty` (one row per reagent).
Builds are our own observation (when a namespace was first seen), so `builds/<day>.parquet` (`version, build, namespace, first_seen, source`) lives on main and survives patch cycles.

Source separation (Jack, 2026-11-18): data copied from a source sits only on the window branch, under that source's folder (`blizzard/`); a new source gets its own folder next to it. Our own tables on main are source-neutral and every row a source fed records it in `source` (`hourly`, `house`, `builds`). Source-specific code stays in the client and mapping layer (`collector/blizzard.py`, `listings.to_frame`, `master.py`); summaries, sales, selection, query and patterns work on the neutral frames.

The hourly rows store item ids only. Names and classes come from the window branch, so the concluded data holds no copied text.

### Sales estimate

Per item, between the previous snapshot P and the current snapshot C (matched by auction id):

- `gone_units`: the quantity of listings in P that are missing in C and were not SHORT in P. These were bought or cancelled. Cancels are counted too, so this is an upper bound.
- `short_gone_units`: the same for listings that were SHORT in P. They expired or were bought; that can't be told apart.
- `partial_units`: the quantity drop of listings that are in both P and C.
- `new_units`: the quantity of listings that are new in C.
- `sold_est = gone_units + partial_units`.
- `span_hours`: the hours between P and C. When it is above 1, a snapshot was missed, and the estimate covers more than one hour.

P is the previous run's listings: a compact Parquet file (`auction_id, item_id, quantity, time_left`, about 2 MB) kept in the Actions cache under one key, overwritten every run. A run ignores and deletes a P older than `copied_days`. When it is missing (the first run, or the cache was evicted), the hour is stored without a sales estimate (NULL) and `span_hours` stays NULL.

### Runs

- **Hourly workflow** (`cron: "35 * * * *"`):
  1. Get a token.
  2. Fetch both listing endpoints with `If-Modified-Since` set to the last stored `observed_at`. On 304, poll again every minute for up to 5 minutes. If nothing new comes, exit 0 with "not modified".
  3. Summarise and filter.
  4. Look up item details for unknown items: first `static-forever`, then `static-classic1x` on 404, with at most 4 parallel requests and a backoff on 429.
  5. Write the hour files to main and any new item details to the window branch.
  6. Commit and push both branches.

  Exit codes: 0 ok or not modified, 1 failed, 2 another run holds the lock.
- **Nightly workflow** (00:50 UTC):
  1. Rebuild the selection and commit it to main.
  2. Apply `summary_retention_days` if it is set above 0.
  3. Refresh the recipes weekly, plus item details older than 7 days.
  4. Rebuild the window branch as a single new orphan commit holding only files of the last `copied_days`.
  5. Force-push it.
- Both workflows share a `concurrency` group, so they never push at the same time. Each step has a `timeout-minutes`.
- The force-push removes old raw data from the branch. GitHub can keep unreachable objects for a while; that is outside our control and is noted in the README.

### Query layer and patterns

- `query/series.py` reads the new tables. The old `snapshot`, `scans`, `watchlist`, `gaps`, `population` and `economy` go away.
- A new `latest_per_item()` replaces the snapshot frame for the patterns and the GUI:
  - `median, min_buyout` from the latest hour.
  - `quantity` from the latest hour.
  - `sales_per_day` as `sold_est` per day over the last 7 days.
  - `median_7d` / `median_30d` as the median of the hourly medians.
  - `low_30d` / `high_30d` from the hourly min and max.

  The patterns' column names stay, so most of them need only small changes.
- Daily or weekly values are aggregated from `hourly` in DuckDB when needed. There are no stored daily tables.
- `economy` becomes `house`. Population is gone; inflation works without it.
- The baseline's "top 300 by sales/day × min buyout with at least 20 sales/day" uses our `sales_per_day`.
- `patterns/builds.py` reads the `builds` table, which now comes from the namespace.

### GUI

- **Status strip:** a credit to Blizzard as the source of the data, worded so it does not suggest endorsement, linking to the README's data section. The exact wording goes in `format.py`.
- **README:** a data and privacy section. It states:
  - the data comes from Blizzard's API "as is";
  - nothing is collected about users;
  - data copied from Blizzard is kept for at most 30 days, while Coppertrail's own hourly conclusions are kept longer;
  - the repo ships no data;
  - Coppertrail is not affiliated with or endorsed by Blizzard.
- **"Pull latest data":** pulls main as before (`--ff-only`). The window branch is fetched into a second checkout inside the data folder (`<data>/window/`, its own git worktree) and set with `git reset --hard origin/window`, followed by `git gc --prune=now` there, because the branch is rewritten daily. The query layer reads both checkouts.
- Remove every view and setting that refers to the old source (credit link, its archive-cutoff state in `states.js`, watchlist mentions).

### Removal of the old source (agreed order)

1. Disable the old collector workflow. **Done 2026-11-18.**
2. Build the new collector, query, patterns and GUI on `dev`, removing the old code as each part is replaced. Delete the 3-row price-table fixture with the old parser.
3. Data repo (each step confirmed by Jack, irreversible):
   1. Copy `handover/` out of the old clone and scrub it: remove all mentions of the old source, and delete `baseline-2026-11-17.md` and the section 5 numbers.
   2. Delete `Jacklog-dev/Coppertrail_Database` on GitHub.
   3. Create it again (private, same name), push main (scrubbed handover, `collector.toml`, workflows) and create the window branch.
   4. Jack adds the `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET` secrets.
   5. Start the first run by hand.
   - GitHub lets an owner restore a deleted repo for 90 days. Only GitHub Support can purge it sooner.
4. Public repo:
   1. Check that `tests/test_no_old_source.py` passes on the final tree.
   2. Replace the whole history with a single new root commit of the final tree on `main` and `dev`, and force-push both.
   3. Delete all `claude/*` branches and their worktrees.
   4. Restart `CHANGELOG.md` without the old entries.
5. This PC: delete the old `private/` clone and replace it with a fresh clone, then delete `data/`, `build/` and `dist/`. Update the auto-memory (remove the cutoff note, add one about the new source and the 30-day rule).
6. Left to Jack: old Claude session transcripts under `~/.claude`, and his own `wow-forever-ah-check` skill.

### Tests

- Offline, with mocked HTTP and small hand-made listing payloads: no real auction data in fixtures.
- Cover:
  - filter rules;
  - quantity-weighted quantiles;
  - the sales estimate (gone, SHORT, partial, a span of 2 hours, missing previous listings);
  - 304 handling;
  - the 404 fallback to `classic1x`;
  - retention pruning;
  - the window-branch rebuild (on a temp git repo);
  - pull with a rewritten branch.
- The existing pattern and GUI tests are moved onto the new frames.
- A test (`tests/test_no_old_source.py`) fails if the old source's name appears in any tracked file.

## Left to the builder

- Module layout inside `coppertrail/collector/` (suggested: `blizzard.py` client, `selection.py`, `summarise.py`, `sales.py`, `master.py`, `window.py`), and how much of `store.py` survives.
- Exact Parquet types (int32 for ids and counts, int64 for prices), the zstd level, and sorting by `item_id`.
- Logging format (no secrets, no prices in workflow logs beyond counts).
- The exact Actions cache key and lock handling.

## Open, outside this design

- Blizzard may change the house ids or the Forever namespaces without notice (`expect_house_name` catches a wrong house).
- Whether Blizzard counts our hourly summaries as "Data". This is Jack's reading for now, and `summary_retention_days` can switch it off.
