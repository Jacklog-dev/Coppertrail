# Raw Data Database on the Pi: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Pi keeps Blizzard's listing responses and item details exactly as sent, for 30 days, in one SQLite file, and hands everything new to the PC on request.

**Architecture:** One stdlib-only script, `pi/coppertrail_raw.py`, with three subcommands: `collect` (hourly listings at :27), `items` (item details at :00, stops at :20) and `export` (read-only stream for the PC over SSH). Two systemd timers run the first two. This replaces the uncommitted first version on this branch (one row per listing, daily files); that code is rewritten in place, not kept.

**Tech Stack:** Python 3.13 stdlib on the Pi (urllib, http.client, json, gzip, sqlite3, fcntl), systemd, bash. Tests run with the repo's `uv run pytest` (Python 3.12) and load the script via `importlib`, as `tests/test_pi_raw.py` does today.

**Spec:** `docs/superpowers/specs/2026-11-24-pi-raw-store-design.md`

## Global Constraints

- Standard library only in `pi/` (the Pi is armv6l).
- One database file, default `/var/lib/coppertrail/raw.sqlite`, overridable by `--db` or `$COPPERTRAIL_DB`. WAL mode.
- Schema exactly as in the spec's "Database" section, with `AUTOINCREMENT` on `snapshot.id` and `item.seq`.
- Listing bodies are stored as received; `encoding` is `gzip` when the response had `Content-Encoding: gzip`, else `identity`. The Pi never compresses.
- Delete cutoff for both tables: `now + 1 h - 30 days` (`last_modified` for snapshots, `fetched_at` for items), compared as ISO strings `%Y-%m-%dT%H:%M:%SZ`.
- Item refresh: no row yet, newest 200 row older than 25 days, or newest row a 404 older than 7 days. Namespaces in order `static-forever-eu`, then `static-classic1x-eu`. Path `/data/wow/item/{id}`, `locale=en_GB`.
- Timing: listings :27 to :55 (unchanged), items :00 to :20. Both take the same `flock` on `<db dir>/.lock`.
- Exit codes: 0 ok or nothing new, 1 failed, 2 locked.
- Never log or print the client ID, secret, token or any body. Logs carry sizes, counts, timings.
- Tests use hand-made fixtures only, no network, no real data.

## Review Focus

1. **Blizzard answers without gzip.** The body is stored as `identity` and the item job still finds its ids. (Task 2, `test_uncompressed_answer_is_stored_as_identity`; Task 3, `test_item_ids_from_identity_body`.)
2. **A broken gzip body** (cut off in transit). It is not stored, the run logs it and exits 1, and the next try can store the hour. (Task 1, `test_broken_gzip_is_refused`.)
3. **Export while a write is open.** The PC reads during the :27 run; the export must see only committed rows and never block or fail. (Task 4, `test_export_during_open_write_sees_committed_rows`.)
4. **The bookmark after deletes.** Ids are never reused after the newest row was deleted, and a bookmark older than the oldest row returns everything left. (Task 1, `test_ids_never_reused`; Task 4, `test_old_bookmark_gets_everything_left`.)
5. **Empty or missing database.** `items` and `export` on a fresh Pi (no file, or no snapshot yet) exit 0 with nothing to do; `export` still prints its end line. (Task 3, `test_items_with_no_snapshot_does_nothing`; Task 4, `test_export_of_missing_db`.)

---

### Task 1: Store (schema, write, delete)

**Files:**
- Modify (rewrite): `pi/coppertrail_raw.py` (store section; drop `_rows`, `day_file`, `day_files`, `_DAY_FILE`, `_KNOWN`, the `listing` table)
- Modify (rewrite): `tests/test_pi_raw.py` (store section; keep the importlib loader, `LM`, `FETCHED`, `ITEMS`, `COMMODITIES`, `SECRET`, `TOKEN`)

**Interfaces:**
- Produces:
  - `DEFAULT_DB = "/var/lib/coppertrail/raw.sqlite"`, `KEEP_DAYS = 30`
  - `connect(db: Path) -> sqlite3.Connection`: creates parents and schema, sets `journal_mode=WAL`, `synchronous=NORMAL`.
  - `connect_ro(db: Path) -> sqlite3.Connection | None`: `file:{db}?mode=ro`, None if the file is missing.
  - `check_body(body: bytes, encoding: str) -> None`: raises `ValueError` if `encoding == "gzip"` and the body does not decompress (decompress only, no JSON parse).
  - `store_snapshot(con, endpoint: str, last_modified: datetime, namespace: str, body: bytes, encoding: str, fetched_at: datetime) -> int | None`: the new `id`, or None if `(endpoint, last_modified)` is already stored. Calls `check_body` first.
  - `store_item(con, item_id: int, namespace: str | None, status: int, body: bytes | None, encoding: str | None, fetched_at: datetime) -> int`: the new `seq`.
  - `newest_last_modified(con, endpoint: str) -> datetime | None`
  - `prune(con, now: datetime, keep_days: int = KEEP_DAYS, lead: timedelta = timedelta(hours=1)) -> tuple[int, int]`: (snapshots deleted, item rows deleted).
  - Keep `iso`, `parse_iso`, `log`, `FetchError`.

- [ ] **Step 1: Write the failing tests** (helper `gz(obj) -> bytes` = `gzip.compress(json.dumps(obj).encode())`)
  - `test_store_keeps_body_as_received`: store `gz(ITEMS)` → `SELECT endpoint, last_modified, encoding, size, body FROM snapshot` is `("items", "2026-11-24T12:22:55Z", "gzip", len(body), body)`.
  - `test_store_twice_writes_once`: second `store_snapshot` with the same endpoint and `LM` returns None; `count(*) == 1`.
  - `test_broken_gzip_is_refused`: `store_snapshot(..., gz(ITEMS)[:-20], "gzip", ...)` raises `ValueError`; table empty.
  - `test_store_item_404_has_no_body`: `store_item(con, 999, None, 404, None, None, FETCHED)` → row `(999, None, 404, None, None)`.
  - `test_prune_deletes_rows_before_they_turn_thirty_days_old`: with `now = 2026-12-24T12:00Z`, a snapshot at `2026-11-24T12:59:59Z` (cutoff is `2026-11-24T13:00:00Z`) and an item fetched at the same time are deleted, ones at `2026-11-24T13:00:01Z` stay; returns `(1, 1)`.
  - `test_ids_never_reused`: store two snapshots, delete the newest row by SQL, store a third → its id is 3.
  - `test_wal_mode`: `PRAGMA journal_mode` is `wal`.

- [ ] **Step 2: Run, expect failures**
  Run: `uv run pytest tests/test_pi_raw.py -q`
  Expected: the new tests fail (old functions, no `body` column).

- [ ] **Step 3: Implement** the store section with the Interfaces above. Schema from the spec; `CREATE TABLE IF NOT EXISTS`, `AUTOINCREMENT`.

- [ ] **Step 4: Run, expect pass**
  Run: `uv run pytest tests/test_pi_raw.py -q` → store tests pass (fetch tests may still fail until Task 2).

- [ ] **Step 5: Commit**
  `git add pi/coppertrail_raw.py tests/test_pi_raw.py` · `git commit -m "Pi raw store: one row per response, body as received"`

### Task 2: Hourly listings (`collect`)

**Files:**
- Modify: `pi/coppertrail_raw.py` (`Client.fetch`, `collect`, `main` with subcommands, `remove_old_store`)
- Modify: `tests/test_pi_raw.py` (fetch section; keep `Resp`, `http_error`, `FakeBlizzard`, `snapshot`, `client`)

**Interfaces:**
- Consumes: Task 1's `connect`, `store_snapshot`, `newest_last_modified`, `prune`.
- Produces:
  - `Client.fetch(endpoint, since) -> tuple[int, datetime | None, str, bytes | None, str | None]`: `(status, last_modified, namespace, body, encoding)`. No decompressing. Token handling, retries and messages unchanged.
  - `Client.token() -> str`: the current or a new token (public, for Task 3).
  - `collect(client, db: Path, now=..., sleep=..., wait=True) -> bool`: same loop as today, but stores bytes; a `ValueError` from `check_body` logs `"{endpoint}: broken body, not stored"` and counts as a failed endpoint for this try (retried in the loop like a not-modified answer until :55, then `ok=False`).
  - `OLD_RAW_DIR = "/var/lib/coppertrail/raw"`; `remove_old_store(old_dir: Path) -> int`: deletes `YYYY-MM-DD.sqlite` files (and `-wal`/`-journal`) in it, then the folder if empty; returns files deleted. `collect` calls it after its first successful store in a run.
  - `main(argv) -> int` with subcommands `collect [--once] [--keep-days N]`, `items`, `export`, `check`; global `--db`. `collect` locks, prunes, then collects, as today.
  - Log line per stored response: `"{endpoint}: stored {size} bytes ({encoding}), Last-Modified {iso}"`.

- [ ] **Step 1: Write the failing tests**
  - `test_new_snapshot_stores_both_endpoints`: two rows, bodies equal to the fake's gzip bytes.
  - `test_uncompressed_answer_is_stored_as_identity`: a `Resp` without `Content-Encoding` → `encoding == "identity"`, body is the plain JSON bytes.
  - Keep, adapted to `db`: `test_not_modified_stores_nothing_and_sends_if_modified_since`, `test_waits_for_a_new_snapshot_until_minute_55`, `test_retries_on_429_and_refreshes_token_on_401`, `test_errors_never_show_the_secret_or_token`, `test_missing_credentials_exit_1`, `test_retry_after_falls_back`.
  - `test_broken_body_is_retried_then_fails`: items answers a cut-off gzip, then 304s until :55 → nothing stored, `collect` returns False.
  - `test_old_day_files_go_after_first_store`: `old/2026-11-23.sqlite`, `old/2026-11-23.sqlite-wal` and `old/notes.txt` exist; after a storing `collect` with `remove_old_store` pointed at `old/`, only `notes.txt` is left. A run that stores nothing leaves all three.
  - `test_collect_log_has_no_body`: capsys output contains `"stored"` and no `"auctions"`.

- [ ] **Step 2: Run, expect failures** · `uv run pytest tests/test_pi_raw.py -q`
- [ ] **Step 3: Implement** with the Interfaces above. `collect` takes `old_dir: Path | None = None` for the test; `main` passes `Path(OLD_RAW_DIR)`.
- [ ] **Step 4: Run, expect pass** · `uv run pytest tests/test_pi_raw.py -q` → all pass
- [ ] **Step 5: Commit** · `git commit -am "Pi collect: store listing responses as received"`

### Task 3: Item details (`items`)

**Files:**
- Modify: `pi/coppertrail_raw.py` (item section)
- Create: `tests/test_pi_items.py` (same importlib loader as `test_pi_raw.py`)

**Interfaces:**
- Consumes: Task 1 `connect`, `store_item`; Task 2 `Client.token()`.
- Produces:
  - `REFRESH_DAYS = 25`, `RETRY_404_DAYS = 7`, `ITEM_LAST_MINUTE = 20`, `ITEM_NAMESPACES = ("static-forever-eu", "static-classic1x-eu")`.
  - `item_ids(body: bytes, encoding: str) -> set[int]`: decompress if gzip, `json.loads`, `{a["item"]["id"] for a in auctions}`.
  - `listed_ids(con) -> set[int]`: union of `item_ids` over the newest snapshot of each endpoint.
  - `due_items(con, ids: set[int], now: datetime) -> list[int]`: missing ids first (ascending), then 200 rows older than 25 days (oldest first), then 404 rows older than 7 days (oldest first).
  - `class ItemClient(client: Client, connect=lambda: http.client.HTTPSConnection("eu.api.blizzard.com", timeout=30), sleep=time.sleep)` with `lookup(item_id) -> tuple[int, str | None, bytes | None, str | None]` = `(status, namespace, body, encoding)`: one kept-alive connection, sends `Accept-Encoding: gzip` and the bearer token, tries the namespaces in order, returns the first 200 or `(404, None, None, None)`. On 429/5xx: backoff (`Retry-After` or `2**attempt * 5` s, 4 retries) then `FetchError`. On 401: new token once. On a dropped connection: reconnect once.
  - `run_items(items: ItemClient, db: Path, now=..., deadline: datetime | None = None) -> bool`: prune not needed here (collect prunes); computes `due_items`, looks up one at a time, commits each answer, stops before a lookup once `now() >= deadline` (default: this hour's :20). Logs `"items: {done} looked up ({found} found, {missing} not found), {left} left"`. True unless a `FetchError` ended it.
  - `main` `items` subcommand: lock, `run_items`, exit 0/1/2.

- [ ] **Step 1: Write the failing tests** (a `FakeConn` with `request(method, url, headers)` / `getresponse()` returning objects with `status`, `getheader(name)`, `read()`, scripted per `(namespace, item_id)`)
  - `test_item_ids_from_gzip_body` / `test_item_ids_from_identity_body`: `ITEMS` → `{2589, 7909}`.
  - `test_due_items_order`: ids `{1,2,3,4}`; 2 has a 200 row 26 days old, 3 a 200 row 10 days old, 4 a 404 row 8 days old → `[1, 2, 4]`.
  - `test_lookup_falls_back_to_classic`: forever 404, classic 200 → `(200, "static-classic1x-eu", body, "gzip")`.
  - `test_lookup_found_nowhere_stores_one_404`: both 404 → one item row, status 404.
  - `test_lookups_reuse_one_connection`: three lookups → `connect` called once.
  - `test_run_stops_at_deadline_and_keeps_what_it_got`: `now` advances 1 min per lookup from :18, deadline :20 → two rows stored, log says `left`.
  - `test_items_with_no_snapshot_does_nothing`: empty db → `run_items` True, no request made.
  - `test_item_log_has_no_secret_or_body`: capsys shows no `SECRET`, `TOKEN` or item name from the fixture body.

- [ ] **Step 2: Run, expect failures** · `uv run pytest tests/test_pi_items.py -q`
- [ ] **Step 3: Implement** with the Interfaces above.
- [ ] **Step 4: Run, expect pass** · `uv run pytest tests/test_pi_items.py tests/test_pi_raw.py -q`
- [ ] **Step 5: Commit** · `git add tests/test_pi_items.py && git commit -am "Pi items: item details as received, refreshed before 30 days"`

### Task 4: Export for the PC (`export`)

**Files:**
- Modify: `pi/coppertrail_raw.py` (export section)
- Create: `tests/test_pi_export.py` (loader as before, plus a test-only parser `read_stream(data: bytes) -> tuple[list[tuple[dict, bytes]], dict]`)

**Interfaces:**
- Consumes: Task 1 `connect_ro`.
- Produces:
  - `export(db: Path, out: BinaryIO, after_snapshot: int, after_item: int) -> tuple[int, int]`: writes, in this order, every snapshot row with `id > after_snapshot` (ascending id), then every item row with `seq > after_item` (ascending seq). Per record: one line of compact JSON + `\n`, then exactly `size` bytes. Snapshot header keys: `table` (`"snapshot"`), `id`, `endpoint`, `last_modified`, `fetched_at`, `namespace`, `encoding`, `size`. Item header keys: `table` (`"item"`), `seq`, `item_id`, `namespace`, `status`, `fetched_at`, `encoding`, `size` (0 when no body). Last line: `{"end": true, "snapshot_max": N, "item_max": M}` (the table maxima, 0 when empty). Returns the counts written. One read transaction for the whole export; rows fetched one at a time (never all bodies in memory).
  - `main` `export --after-snapshot ID --after-item SEQ` (both default 0) writes to `sys.stdout.buffer`; logs nothing to stdout (counts go to stderr).

- [ ] **Step 1: Write the failing tests**
  - `test_export_streams_new_rows_in_order`: 3 snapshots, 2 items; `after_snapshot=1, after_item=0` → snapshot ids `[2, 3]`, item seqs `[1, 2]`, bodies byte-equal, end line `{"end": True, "snapshot_max": 3, "item_max": 2}`.
  - `test_export_404_item_has_no_bytes`: header `size == 0`, next record follows right away.
  - `test_old_bookmark_gets_everything_left`: ids 1–3 stored, 1 pruned, `after_snapshot=0` → `[2, 3]`.
  - `test_export_during_open_write_sees_committed_rows`: a second connection holds `BEGIN IMMEDIATE` with an uncommitted insert → export returns only the committed rows, no exception.
  - `test_export_of_missing_db`: no file → output is only the end line with maxima 0; `main(["--db", missing, "export"]) == 0`.
  - `test_export_never_writes`: file mtime and `snapshot` count unchanged after export.

- [ ] **Step 2: Run, expect failures** · `uv run pytest tests/test_pi_export.py -q`
- [ ] **Step 3: Implement** with the Interfaces above.
- [ ] **Step 4: Run, expect pass** · `uv run pytest tests/test_pi_*.py -q`
- [ ] **Step 5: Commit** · `git add tests/test_pi_export.py && git commit -am "Pi export: stream new rows to the PC"`

### Task 5: Units, install, docs

**Files:**
- Modify: `pi/coppertrail-raw.service` (`ExecStart=... coppertrail_raw.py collect`, `Environment=COPPERTRAIL_DB=/var/lib/coppertrail/raw.sqlite`)
- Create: `pi/coppertrail-items.service` (as the raw one, `ExecStart=... items`, `TimeoutStartSec=25min`), `pi/coppertrail-items.timer` (`OnCalendar=*-*-* *:00:00 UTC`, `AccuracySec=30s`, `Persistent=true`)
- Modify: `pi/set-blizzard-secret.sh` (`--check` becomes the `check` subcommand)
- Modify: `pi/install.sh` (install and enable both timers; `--status` shows both timers, last 10 log lines of each service, `ls -lh` of the db and its `-wal`)
- Modify: `pi/README.md`, `CLAUDE.md`, `.gitignore` (add `*.sqlite-wal`, `*.sqlite-shm` beside `*.sqlite`)
- Create: `tests/test_pi_units.py`

**Interfaces:**
- Consumes: Task 2–4 subcommand names.

- [ ] **Step 1: Write the failing test** `test_units_call_existing_subcommands`: each `pi/*.service` `ExecStart` ends with a subcommand that `main`'s parser accepts; each `.timer` has a matching `.service`; `install.sh` names every unit file in `pi/`; `set-blizzard-secret.sh` calls `coppertrail_raw.py" check` or `'$SCRIPT' check` (a subcommand, not `--check`).
- [ ] **Step 2: Run, expect failure** · `uv run pytest tests/test_pi_units.py -q`
- [ ] **Step 3: Write the units and install.sh.**
- [ ] **Step 4: Docs.** `pi/README.md`: layout, the three subcommands, the export format, deploy steps, status. `CLAUDE.md`: replace the Status paragraph, the "Raspberry Pi" section and the "Repositories" section to say: the Pi's raw data database is the only data source; the GitHub data repository and its workflows are gone; the collector, `ui/pull.py` and the `copied-data`/`window/` notes describe the old pipeline and will be replaced by "our" database on the PC (next project). Keep the public-repo rules (no data in commits, credentials never printed), the 30-day rule and the design rules. Short bullets, no history.
- [ ] **Step 5: Run everything** · `uv run pytest -q` and `uv run ruff check .` and `uv run ruff format --check .` → all green.
- [ ] **Step 6: Commit** · `git add pi tests/test_pi_units.py CLAUDE.md docs/superpowers/specs/2026-11-24-pi-raw-store-design.md docs/superpowers/plans/2026-11-24-pi-raw-store.md .gitignore .gitattributes && git commit -m "Pi units for collect and items; docs for the raw data database"`

### Task 6: Deploy and check on the Pi (needs Jack's go before Step 1)

- [ ] **Step 1: Deploy** outside :25–:56 and :00–:20. `scp -r pi coppertrail@coppertrail-pi:/tmp/pi` then `ssh coppertrail@coppertrail-pi "sudo bash /tmp/pi/install.sh"`. Expected: "Installed", both timers listed by `--status`.
- [ ] **Step 2: First listing hour.** After the next :27 run, `sudo bash install.sh --status` shows `stored ... bytes (gzip)` for both endpoints. Record Blizzard's compressed sizes and the run time. Check that `/var/lib/coppertrail/raw/` is gone.
- [ ] **Step 3: First item run.** After :00, the log shows lookups done and left; note the rate per minute and the RAM peak (`systemctl show coppertrail-items.service -p MemoryPeak`).
- [ ] **Step 4: Export from the PC.** `ssh coppertrail@coppertrail-pi "python3 /opt/coppertrail/coppertrail_raw.py export --after-snapshot 0 --after-item 0" > <scratchpad>/export.bin` and parse it with the test parser: record counts match `SELECT count(*)` on the Pi. Delete the file afterwards (it is Blizzard data, never in the repo).
- [ ] **Step 5: Update the spec's Measurements** with the real sizes, run times and item rate, and the first-fill estimate. Commit: `git commit -am "Pi raw store: measured on the Pi"`.
