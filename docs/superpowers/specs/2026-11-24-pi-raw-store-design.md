# Raw data database on the Raspberry Pi

Agreed with Jack on 2026-11-24. Replaces the first version of this spec from the same morning (one row per listing in daily files, about 10 GB for 30 days).

## Why

The GitHub data repository is gone. The Pi is the only source of data. It keeps Blizzard's data exactly as sent, for 30 days, in one database: the **raw data database**. Coppertrail on the PC fetches from it and turns it into our own data, which it keeps forever in a second database of its own (planned next, not part of this spec). The two databases are separate: neither reads the other directly. The PC only gets what the Pi hands out.

The raw data database must hold everything the Item Detail panel will need: listings every hour, plus item details (names, classes, vendor prices).

## Goals

- Every hour, store both listing responses of house 111 (items and commodities) as Blizzard sent them.
- Store item details for every item that appears in the listings, and keep them fresh.
- Keep the last 30 days; delete older data automatically.
- Use as little of the Pi as possible: no parsing for reads, no compressing, no searching.
- A simple way for the PC to fetch everything it does not have yet.
- About 2 GB for 30 days.

## Non-goals

- Our own database on the PC and anything that turns raw data into prices (next project).
- The GUI views, including Item Detail.
- Recipes, media, icons, the game build.

## Anti-goals

- One row per listing, or anything else that makes the store tens of millions of rows.
- The Pi doing summaries, statistics or per-item lookups for the PC.
- Any data in the public repo.

## Constraints

- Raspberry Pi 1 B+: armv6l, 426 MB RAM, 29 GB SD card, Raspberry Pi OS Lite 32-bit, Python 3.13, SQLite 3.46. Standard library only.
- Blizzard's terms: data copied from the API is kept at most 30 days. That covers listings and item details. At most 36,000 requests per hour.
- Credentials are never logged, printed or committed (unchanged: `/etc/coppertrail/blizzard.env`).
- The public repo holds code only.

## Measurements (on the Pi, 2026-11-24, newest snapshot rebuilt as Blizzard's JSON)

| | JSON | gzip -6 | Unpack and parse on the Pi |
|---|---|---|---|
| Items, 152,635 listings | 15.3 MB | 1.65 MB | about 23 s |
| Commodities, 116,161 listings | 10.1 MB | 1.15 MB | about 15 s |

So one hour is about 2.8 MB compressed, and 30 days about 2 GB. xz saves another third but takes 2 minutes per response on the Pi, so it is out. The Pi asks Blizzard for gzip (`Accept-Encoding: gzip`) and stores the bytes it receives without compressing anything.

**Measured after deployment (2026-11-24, 15:23 UTC snapshot):**

| | Result |
|---|---|
| Blizzard's own gzip | items 1.71 MB (159,932 listings), commodities 1.21 MB (122,623): **2.9 MB per hour, about 2.1 GB for 30 days** |
| `collect` | 6.3 s CPU for both responses |
| `items`, first fill | 7,128 items in 10 min 45 s (about 11 per second over the kept-alive connection): 6,915 found (2,820 of them only in `static-classic1x-eu`), 213 found nowhere; item bodies 5.5 MB in total; peak memory 106 MB of 426 MB |
| `export` to the PC over SSH | 2.9 MB (one hour) in 9 s; a full 30-day catch-up would take about 1.5 to 2 hours |

The 25-day refresh brings all items due on the same day; at this rate that is one 11-minute run, so it needs no spreading.

## Approaches

1. **One row per listing, one file per day** (this morning's version). Fast per-item reads on the Pi, but 170 million rows and 10 GB for 30 days. Its reason, per-item reads on the Pi, is gone: the PC does all reading. Rejected.
2. **One row per response, the body as sent (chosen).** 1,440 listing rows for 30 days (items and commodities per hour). Writing costs almost nothing, deleting is one row, reading for the PC is handing over bytes.
3. **Plain gzip files in a folder, no database.** Just as cheap, but Jack wants one database, and item details would need a second scheme. Rejected.

## Design

### Database

One SQLite file: `/var/lib/coppertrail/raw.sqlite`. WAL mode, so the PC's reads never block the hourly write.

```sql
CREATE TABLE snapshot (
    id            INTEGER PRIMARY KEY,   -- grows with every stored response; the PC's bookmark
    endpoint      TEXT NOT NULL,         -- 'items' | 'commodities'
    last_modified TEXT NOT NULL,         -- Blizzard's Last-Modified, ISO 8601 UTC
    fetched_at    TEXT NOT NULL,         -- when the Pi received it, ISO 8601 UTC
    namespace     TEXT NOT NULL,
    encoding      TEXT NOT NULL,         -- 'gzip' or 'identity': how body is stored
    size          INTEGER NOT NULL,      -- bytes of body
    body          BLOB NOT NULL,         -- the response body exactly as received
    UNIQUE (endpoint, last_modified)
);

CREATE TABLE item (
    seq        INTEGER PRIMARY KEY,      -- grows with every stored lookup; the PC's bookmark
    item_id    INTEGER NOT NULL,
    namespace  TEXT,                     -- 'static-forever-eu', 'static-classic1x-eu', or NULL if not found
    status     INTEGER NOT NULL,         -- HTTP status of the answer that counts (200, or 404 if found nowhere)
    fetched_at TEXT NOT NULL,
    encoding   TEXT,                     -- as in snapshot; NULL when there is no body
    body       BLOB                      -- the response body exactly as received; NULL on 404
);
CREATE INDEX item_by_id ON item (item_id, fetched_at);
```

- Listing bodies are stored as received. If Blizzard ever answers uncompressed, the body is stored as `identity` (no compressing on the Pi; storage grows, which the log shows).
- Storing the same snapshot again writes nothing (unique key).
- `id` and `seq` only grow (`INTEGER PRIMARY KEY` without reuse: use `AUTOINCREMENT`), so "everything after N" is a reliable bookmark for the PC even after deletes.
- Deleted rows free their pages inside the file, and new rows reuse them. The file settles at about 2 GB. No `VACUUM`.

### Hourly job

Unchanged where not mentioned: `coppertrail-raw.timer` at :27 UTC, `If-Modified-Since` with the newest stored `last_modified`, retry every 5 minutes until :55, `flock` lock, user `coppertrail`, exit codes 0 / 1 / 2, logs to journald.

1. **Delete** every listing row with `last_modified <= now + 1 h - 30 days`, and every item row with `fetched_at <= now + 1 h - 30 days`. (The item job never adds an item row it would have to delete within the hour, since it refreshes at 25 days.)
2. **Fetch** both listing endpoints and store each body as received.
3. **Log** sizes, counts and timings, never bodies or credentials.

### Item job (separate, so listings never wait)

A second unit, `coppertrail-items.timer`, starts `coppertrail_raw.py items` at :00 every hour. It stops looking things up at :20 at the latest, so it never overlaps the listing job (:27 to :55); both also take the same `flock`. If an item run overruns, the listing job waits for the lock until :35 (built after the final review), so the listing hour is not lost. (My call: the listing hour is the data that cannot be fetched again; item details can.)

1. Unpack the newest stored body of each endpoint once to collect the item ids (about 20 s on the Pi; the parsed data is dropped right away). This works the same in hours where the listing job stored nothing.
2. Look up, oldest need first:
   - every id with no item row yet;
   - every id whose newest item row is older than 25 days (so a refresh always lands before the delete);
   - every id whose newest row is a 404 older than 7 days (new items may appear later).
3. One request at a time over one kept-alive HTTPS connection (`http.client`), backoff on 429, until the list is done or :20. Order: `static-forever-eu`, then `static-classic1x-eu` on 404; store the answer that counts (the 200 body, or one 404 row if both say 404). Each answer is committed on its own, so a stopped run loses nothing. Items no longer listed are not refreshed and fall out after 30 days.

The first fill of about 7,000 items (about 11,000 requests with the fallback) takes as many hourly runs as it needs; the log shows the rate, and the builder sizes the first-fill estimate from it. After that it is a handful per run, plus the refresh.

### Handing data to the PC

The PC fetches over SSH (key login, as today). A read-only command on the Pi streams what the PC asks for:

```
python3 /opt/coppertrail/coppertrail_raw.py export --after-snapshot ID --after-item SEQ
```

Output on stdout, one record after another: one JSON header line (`{"table": "snapshot", "id": ..., "endpoint": ..., "last_modified": ..., "fetched_at": ..., "namespace": ..., "encoding": ..., "size": N}`, or the matching fields for `item`), followed by exactly `size` bytes of body (none for a 404 item row). A last line `{"end": true, "snapshot_max": ..., "item_max": ...}` closes the stream. The Pi only reads rows by primary key and copies bytes; it never unpacks or parses for an export. The database is opened read-only (`mode=ro`), so an export never writes.

The PC remembers the highest `id` and `seq` it has stored in its own database. If the PC was off for days it gets everything since then, as long as it is under 30 days. If its bookmark is older than the oldest row, it simply gets everything that is left (the gap is lost; the PC can tell from the ids).

### Old store

The first version (daily files under `/var/lib/coppertrail/raw/`, one row per listing) is replaced. `install.sh` stops the old timer before installing the new script. The old day files are deleted once the new store has stored its first hour.

### Code

`pi/` in the public repo, as before: `coppertrail_raw.py` (subcommands `collect`, `items`, `export`), both timers and services, `install.sh`, `set-blizzard-secret.sh`, the units, `README.md`. Tests in `tests/test_pi_raw.py`, offline, hand-made fixtures (made-up listings and items, never real data). CLAUDE.md is updated: no GitHub data repository, no workflows, the Pi as the only source.

## Left to the builder

- Exact retry and timeout values; the shape of the log lines.
- How item ids are pulled from the bodies (full `json.loads` or a faster scan).
