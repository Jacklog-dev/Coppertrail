# Blizzard Source Implementation Plan

> **Superseded in part (2026-11-18):** copied data no longer lives on a `window` branch. It moves as the `copied-data` GitHub Actions artifact and is unpacked into `<data>/window/` (not in git). `docs/architecture.md` describes the current design.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old data source with Blizzard's Game Data API: an hourly collector in GitHub Actions, a 30-day window for copied data, our own conclusions kept long-term, patterns and GUI on the new tables. Then remove every trace of the old source.

**Architecture:**
- `coppertrail/collector/` is rewritten around a Blizzard client. The hourly run fetches house 111, summarises the selected items and compares with the previous listings, then writes write-once hour files to the data repo's `main` branch. A nightly run rebuilds the item selection, refreshes item details and recipes on a `window` branch, and rewrites that branch to the last 30 days.
- The query layer reads both checkouts (`<data>/` = main, `<data>/window/` = window).

**Tech Stack:** Python 3.12, uv, httpx, pandas, pyarrow, DuckDB, pytest, pywebview front end (plain JS), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-18-blizzard-source-design.md` (read it first; it holds the verified API facts and the decisions).

## Global Constraints

- House: region `eu`, ruleset `2`, house `111`, name must contain `Alliance`. Namespaces `dynamic-forever-eu`, `static-forever-eu`, fallback `static-classic1x-eu`, locale `en_GB`.
- The house index URL needs its trailing slash: `/data/wow/ruleset/2/auctions/`.
- Credentials: `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET`, otherwise `config_dir()/blizzard.toml` table `[blizzard]` with `client_id`, `client_secret`. Never log or print either, nor the token.
- Prices are copper per unit, as int64. Commodities: `unit_price`. Items: `buyout / quantity`. Bid-only listings count in `quantity`/`auctions`, but not in prices.
- Quantiles are weighted by quantity: sort by unit price, take the first price whose cumulative quantity is `>= q × total`, and round to int.
- Selection defaults:
  - `exclude_qualities=["POOR"]`
  - `min_median={COMMON=50}`
  - `exclude_classes=["Recipe"]`
  - `equipment_classes=["Armor","Weapon"]`
  - `equipment_min_quality="EPIC"`
  - `include_unclassified=true`
  - `max_items=2000`, `rank_days=7`, `keep_rank=2200`
- Retention: `copied_days=30` (listings state, item details, recipes); `summary_retention_days=0` (0 = keep for good).
- Quality order: POOR < COMMON < UNCOMMON < RARE < EPIC < LEGENDARY < ARTIFACT < HEIRLOOM.
- Days and hours are UTC. `hour` = `observed_at` (the snapshot's `Last-Modified`) floored to the hour.
- Test fixtures are hand-made. No real auction payloads, no copied price rows.
- No Qt. No hex colours or font names outside `tokens.css`. JS writes data with `textContent`.
- Session branches merge into `dev`. `main` and tags only on Jack's call. Every irreversible step (repo delete, force-push, local deletes) needs Jack's explicit yes in chat for that step.
- The workflows run only in the private data repo. Nothing in the public repo may name or reference the private repo, except the README's credit link target.

## Review Focus

1. **Blizzard answers 200 with an unchanged `Last-Modified` instead of 304.** Expected: treated as not modified, nothing written. Tests: Task 0.3 (client) and Task 1.4 (run).
2. **A rerun of the same snapshot** (the workflow is retried, or the hour file already exists). Expected: no second file, no changed bytes, no empty commit. Test: Task 1.4.
3. **A previous-listings state from another house, or older than `MAX_SPAN_HOURS` (6).** Expected: the sales columns are NULL, `span_hours` is NULL, the prices are still written. Test: Task 1.2.
4. **The token expires or returns 401 mid-run.** Expected: one new token, then a retry of the request. A second 401 fails the run with exit 1 and no secret in the message. Test: Task 0.3.
5. **The GUI pulls after `window` was force-pushed, or `window/` does not exist yet.** Expected: the pull succeeds, `window/` matches `origin/window`, and main is pulled `--ff-only` as before. Test: Task 4.2.

## Sessions and order

| Phase | Session | Work package | Needs | Files it owns |
|---|---|---|---|---|
| 0 | this session | WP0 foundation | none | `collector/legacy/` (move only), `collector/{config,credentials,throttle,lock,blizzard,store,__main__}.py`, `tests/blizzard_fixtures.py`, `.gitignore` |
| 1 (parallel) | A | WP1 hourly run | WP0 on dev | `collector/{listings,summarise,sales,selection,hourly}.py` |
| 1 | B | WP2 master data + nightly | WP0 | `collector/{master,window,nightly}.py` |
| 1 | C | WP3 query, patterns, GUI data | WP0 | `query/*`, `patterns/*`, `ui/{bridge,viewdata,movers,patternview}.py`, their tests |
| 1 | D | WP4 GUI chrome + README | WP0 | `ui/{pull,app,format}.py`, `ui/web/js/{statusstrip,states}.js`, `README.md` |
| 1 | E | WP6 handover scrub | none | `private-next/handover/` (outside git) |
| 2 | this session | WP5 workflows + new data repo | WP1, WP2, WP6 merged | `private-next/` (new data repo) |
| 3 | this session | WP7 purge and final check | all | public repo history, local folders, CLAUDE.md, CHANGELOG, docs |

Each phase-1 session works in its own worktree from `dev` after WP0 is merged. It deletes the old code it replaces, keeps `uv run pytest -q` and `uv run ruff check .` green for its own files, and merges into `dev` when done. Old tests that test removed code are deleted by the session that removes that code.

The temporary package `collector/legacy/` (Task 0.0) keeps the old code working until WP1 and WP3 are both merged. WP7 deletes it.

---

## WP0: Foundation (this session, before phase 1)

### Task 0.0: Park the old collector

**Files:**
- Move (with `git mv`): `coppertrail/collector/{api,parse,watchlist,gaps,run,config,store}.py` to `coppertrail/collector/legacy/` (plus an `__init__.py`).
- Modify: every import of them (`query/*`, `ui/*`, `patterns/*`, `collector/__main__.py`, `tests/*`), now pointing to `coppertrail.collector.legacy.<module>`.

- [ ] **Step 1:** Move the files and repoint the imports. No code changes besides imports.
- [ ] **Step 2:** Run `uv run pytest -q` and `uv run ruff check .`. Expected: the same pass count as before the move.
- [ ] **Step 3:** Commit `Park the old collector in collector/legacy`.

The legacy package keeps the old query, patterns and GUI code working until WP1 and WP3 replace them. WP1 deletes `legacy/{api,parse,watchlist,gaps,run}.py`, WP3 removes the last imports of `legacy/store.py` and `legacy/config.py`, and WP7 deletes the package.

### Task 0.1: Config with selection and retention

**Files:**
- Create: `coppertrail/collector/config.py` (new; the old one is now in `legacy/`)
- Test: `tests/test_collector_config.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Blizzard(region="eu", ruleset=2, house=111, expect_house_name="Alliance", locale="en_GB", rate_per_s=20.0, timeout_s=60.0, max_retries=4)`
  - `class Selection(...)` with the defaults from Global Constraints. `min_median` is `dict[str, int]`.
  - `class Retention(copied_days=30, summary_retention_days=0)`
  - `class Config(blizzard, selection, retention, data_dir: Path, window_dir: Path, state_dir: Path)`
  - `load_config(data_dir: Path) -> Config`: reads `data_dir/collector.toml` if present, sets `window_dir = data_dir/"window"` and `state_dir = data_dir/".state"`, and rejects unknown keys with `ValueError`.
  - `QUALITY_ORDER: tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

```python
def test_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.blizzard.house == 111 and cfg.blizzard.ruleset == 2
    assert cfg.selection.exclude_classes == ("Recipe",)
    assert cfg.selection.min_median == {"COMMON": 50}
    assert cfg.selection.equipment_min_quality == "EPIC"
    assert cfg.retention.copied_days == 30 and cfg.retention.summary_retention_days == 0
    assert cfg.window_dir == tmp_path / "window"

def test_toml_overrides(tmp_path):
    (tmp_path / "collector.toml").write_text('[selection]\nmax_items = 500\nmin_median = { COMMON = 80 }\n')
    cfg = load_config(tmp_path)
    assert cfg.selection.max_items == 500 and cfg.selection.min_median == {"COMMON": 80}

def test_unknown_key_rejected(tmp_path):
    (tmp_path / "collector.toml").write_text("[selection]\nmax_itemz = 5\n")
    with pytest.raises(ValueError, match="max_itemz"):
        load_config(tmp_path)

def test_bad_quality_rejected(tmp_path):
    (tmp_path / "collector.toml").write_text('[selection]\nequipment_min_quality = "SHINY"\n')
    with pytest.raises(ValueError, match="SHINY"):
        load_config(tmp_path)
```

- [ ] **Step 2:** Run `uv run pytest tests/test_collector_config.py -q`. Expected: FAIL (import error).
- [ ] **Step 3:** Implement as in Interfaces. Use tuples for list fields so the dataclasses stay frozen.
- [ ] **Step 4:** Run the same command. Expected: 4 passed.
- [ ] **Step 5:** Commit `Collector config: Blizzard house, selection, retention`.

### Task 0.2: Credentials, throttle, lock

**Files:**
- Create: `coppertrail/collector/credentials.py`, `coppertrail/collector/throttle.py` (copy `Throttle` and `parse_retry_after` from `legacy/api.py` unchanged), `coppertrail/collector/lock.py` (copy `RunLock` and `LockError` from `legacy/run.py` unchanged)
- Test: `tests/test_collector_credentials.py`

**Interfaces:**
- Produces:
  - `load_credentials(env: Mapping[str,str] = os.environ, folder: Path | None = None) -> tuple[str, str]`
  - `class CredentialsError(Exception)`, whose message names the env vars and the file path but never a value.

- [ ] **Step 1: Write the failing tests**

```python
def test_env_wins(tmp_path):
    (tmp_path / "blizzard.toml").write_text('[blizzard]\nclient_id="f"\nclient_secret="g"\n')
    assert load_credentials({"BLIZZARD_CLIENT_ID": "a", "BLIZZARD_CLIENT_SECRET": "b"}, tmp_path) == ("a", "b")

def test_file_fallback(tmp_path):
    (tmp_path / "blizzard.toml").write_text('[blizzard]\nclient_id="f"\nclient_secret="g"\n')
    assert load_credentials({}, tmp_path) == ("f", "g")

def test_missing_names_sources_not_values(tmp_path):
    with pytest.raises(CredentialsError) as e:
        load_credentials({"BLIZZARD_CLIENT_ID": "only-id"}, tmp_path)
    assert "BLIZZARD_CLIENT_SECRET" in str(e.value) and "only-id" not in str(e.value)
```

- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement. `folder` defaults to `coppertrail.query.settings.config_dir()`.
- [ ] **Step 4:** Run it. Expected: 3 passed. Then copy the existing throttle and lock tests next to the new modules, and run them too. Expected: pass.
- [ ] **Step 5:** Commit `Collector: credentials loader; throttle and lock in their own modules`.

### Task 0.3: Blizzard client

**Files:**
- Create: `coppertrail/collector/blizzard.py`
- Create: `tests/blizzard_fixtures.py`: hand-made payload builders `item_auction(id, item_id, qty, buyout=None, bid=None, time_left="LONG")`, `commodity(id, item_id, qty, unit_price, time_left="LONG")`, `item_detail(item_id, quality="COMMON", cls="Trade Goods", cls_id=7, sub="Cloth", sub_id=5, sell=10)`, and `mock_transport(routes: dict[str, Callable[[httpx.Request], httpx.Response]]) -> httpx.MockTransport`.
- Test: `tests/test_blizzard_client.py`

**Interfaces:**
- Consumes: `Config.blizzard`, `Throttle`.
- Produces:
  - `class BlizzardError(Exception)`, with a `status: int | None` attribute.
  - `@dataclass class Fetched: items: dict; commodities: dict; last_modified: datetime; namespace: str`
  - `class BlizzardClient(cfg: Blizzard, client_id: str, client_secret: str, transport: httpx.BaseTransport | None = None, sleep=time.sleep)`, a context manager, with:
    - `get(path: str, namespace: str, if_modified_since: datetime | None = None) -> httpx.Response`. It adds the `namespace-<region>`, locale and bearer token; throttles; on 429/503 waits `Retry-After` and retries; on 401 refreshes the token once, then raises.
    - `house_name() -> str`, from `/data/wow/ruleset/{ruleset}/auctions/` (trailing slash).
    - `listings(since: datetime | None) -> Fetched | None`. It fetches `/auctions/{house}` and `/auctions/{house}/commodities`. It returns None on 304, or when `last_modified == since` for either endpoint.
    - `item(item_id: int) -> tuple[dict | None, str]`. It tries `static-forever`, then `static-classic1x`, and returns `(None, "")` if both give 404. The string is the response's `battlenet-namespace` header.
    - `json(path, namespace) -> dict`, used by WP2 for professions and recipes.
    - `static_namespace() -> str`: the `battlenet-namespace` header of `/data/wow/item-class/index` in `static-forever`, for example `static-1.60.1_70399-forever-eu`. The dynamic listings response carries no build, so this is the build source.

- [ ] **Step 1: Write the failing tests** (all with `mock_transport`)

```python
def test_token_and_headers_and_namespace(): ...   # token POST once; GET carries Bearer, namespace=dynamic-forever-eu, locale=en_GB
def test_304_returns_none(): ...
def test_same_last_modified_returns_none(): ...   # Review Focus 1, client side
def test_429_honours_retry_after(): ...           # sleep called with 3.0 for "Retry-After: 3"
def test_401_refreshes_token_once_then_raises():  # Review Focus 4
    # first GET 401 -> new token -> GET 200 ok; with two 401s in a row: BlizzardError(status=401),
    # and neither the client id nor the secret appears in str(err)
def test_item_falls_back_to_classic1x(): ...      # forever 404, classic1x 200 -> namespace "static-classic1x-eu"
def test_item_unknown_everywhere(): ...           # (None, "")
def test_house_index_uses_trailing_slash(): ...   # request path ends with "/auctions/"
def test_static_namespace_from_header(): ...      # returns "static-1.60.1_70399-forever-eu"
```

- [ ] **Step 2:** Run `uv run pytest tests/test_blizzard_client.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. The token comes from `POST https://oauth.battle.net/token` with `grant_type=client_credentials` and basic auth. `last_modified` is parsed with `email.utils.parsedate_to_datetime` and converted to UTC.
- [ ] **Step 4:** Run it. Expected: 9 passed.
- [ ] **Step 5:** Commit `Collector: Blizzard API client`.

### Task 0.4: Store for the new layout

**Files:**
- Create: `coppertrail/collector/store.py` (new; the old one is now in `legacy/`)
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - Tables. `branch` is `"main"` or `"window"`. `layout` is `"hour"` for `<name>/<YYYY-MM-DD>/<HH>.parquet`, or `"day"` for `<name>/<YYYY-MM-DD>.parquet`. All columns are nullable unless stated otherwise.
    - `HOURLY` (main, hour): `item_id int32 not null`, `hour ts not null`, `observed_at ts not null`, `min int64`, `p25 int64`, `median int64`, `p75 int64`, `quantity int32 not null`, `auctions int32 not null`, `gone_units int32`, `partial_units int32`, `short_gone_units int32`, `new_units int32`, `span_hours float32`, `source string not null` (= "blizzard").
    - `HOUSE` (main, hour): `hour`, `observed_at`, `auctions int32`, `units int64`, `gold_listed int64`, `gone_auctions int32`, `new_auctions int32`, `sold_value_est int64`.
    - `SELECTION` (main, day): `day date32`, `item_id int32`, `reason string` ("rule" | "unclassified"), `rank int32`.
    - `BUILDS` (main, day): `version string`, `build int32`, `namespace string`, `first_seen ts`.
    - `ITEMS` (window, day): `item_id int32`, `found bool`, `name`, `quality`, `class_id int16`, `class`, `subclass_id int16`, `subclass`, `required_level int16`, `sell_price int64`, `purchase_price int64`, `item_level int16`, `namespace`, `fetched_at ts`.
    - `RECIPES` (window, day): `recipe_id int32`, `name`, `profession`, `crafted_item_id int32`, `crafted_qty float32`, `reagent_id int32`, `reagent_qty int16`, `fetched_at ts`.
  - `TABLES: dict[str, Table]`. `ts` = `pa.timestamp("us", tz="UTC")`.
  - `class Store(data_dir: Path, window_dir: Path)` with:
    - `path(table, when: datetime | date) -> Path`
    - `write_hour(table, observed_at: datetime, df: pd.DataFrame) -> Path | None`: atomic, zstd level 9, sorted by `item_id` where present. Returns None and writes nothing if the file exists with the same `observed_at`.
    - `write_day(table, day: date, df) -> Path`: replaces the file.
    - `files(table, start: date | None, end: date | None) -> list[Path]`
    - `read(table, start=None, end=None) -> pa.Table | None`

- [ ] **Step 1: Write the failing tests**

```python
def test_hour_path_layout(tmp_path):
    s = Store(tmp_path, tmp_path / "window")
    t = datetime(2026, 11, 18, 12, 22, 53, tzinfo=UTC)
    assert s.path(HOURLY, t) == tmp_path / "hourly" / "2026-11-18" / "12.parquet"
    assert s.path(ITEMS, t.date()) == tmp_path / "window" / "items" / "2026-11-18.parquet"

def test_write_hour_once(tmp_path):                 # Review Focus 2, store side
    p = s.write_hour(HOURLY, t, frame); b = p.read_bytes()
    assert s.write_hour(HOURLY, t, frame) is None and p.read_bytes() == b

def test_schema_enforced(tmp_path): ...             # extra column -> ValueError; int32 ids on read
def test_files_by_day_range(tmp_path): ...          # only files of 17-18 Nov for start=17, end=18
```

- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement. Keep the `_atomic_write` helper. Drop staging, upsert and every old table.
- [ ] **Step 4:** Run it. Expected: 4 passed.
- [ ] **Step 5:** Commit `Store: hour and day files on main and window`.

### Task 0.5: CLI skeleton, legacy shim, ignore rules

**Files:**
- Rewrite: `coppertrail/collector/__main__.py` (the old `run` and `gaps` commands go away)
- Modify: `.gitignore` (add `private-next/`)
- Test: `tests/test_collector_cli.py`

**Interfaces:**
- Produces: `python -m coppertrail.collector [--data-dir DIR] [-v] {hourly,nightly}`.
  - `hourly` calls `coppertrail.collector.hourly.main(cfg) -> int`, and `nightly` calls `coppertrail.collector.nightly.main(cfg) -> int`. Both are imported lazily.
  - The data dir defaults to `$COPPERTRAIL_DATA`, else `./private`.
  - Exit codes: 0 ok or not modified, 1 failed, 2 lock held.
  - Logs go to `<data>/logs/collector.log` and stderr, with counts only and no prices.

- [ ] **Step 1:** Write failing tests:
  - `test_unknown_command_exits_2_from_argparse`;
  - `test_hourly_dispatches(monkeypatch)`: patches `coppertrail.collector.hourly.main` to return 0, and asserts exit 0 and that it received a `Config` with the given data dir;
  - `test_lock_held_exits_2`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement. Create `hourly.py` and `nightly.py` as stubs whose `main` raises `NotImplementedError`. WP1 and WP2 replace them.
- [ ] **Step 4:** Run the whole suite: `uv run pytest -q`. Expected: green. The old code still runs from `collector/legacy/`; only tests of the old CLI commands are deleted.
- [ ] **Step 5:** Commit `Collector CLI: hourly and nightly commands`. Merge into `dev`. Then start the phase-1 sessions.

---

## WP1: Hourly run (session A)

### Task 1.1: Listings frame and per-item summary

**Files:**
- Create: `coppertrail/collector/listings.py`, `coppertrail/collector/summarise.py`
- Test: `tests/test_summarise.py`

**Interfaces:**
- Consumes: `Fetched` (Task 0.3).
- Produces:
  - `to_frame(f: Fetched) -> pd.DataFrame` with columns `auction_id int64, item_id int32, quantity int32, unit float64 (NaN for bid-only), time_left str, kind str ("item"|"commodity")`.
  - `weighted_quantile(prices: np.ndarray, weights: np.ndarray, q: float) -> float`
  - `summarise(frame: pd.DataFrame) -> pd.DataFrame` with columns `item_id, min, p25, median, p75, quantity, auctions` (prices Int64, NULL when an item has only bid-only listings).
  - `house_totals(frame) -> dict`: `auctions, units, gold_listed`.

- [ ] **Step 1: Write the failing tests**

```python
def test_unit_price_from_buyout_and_commodity():
    f = to_frame(fetched(items=[item_auction(1, 10, 4, buyout=400)], commodities=[commodity(2, 20, 5, 30)]))
    assert f.set_index("auction_id").loc[1, "unit"] == 100 and f.set_index("auction_id").loc[2, "unit"] == 30

def test_weighted_quantiles():
    s = summarise(frame_of([(10, 1, 100), (10, 3, 200)]))   # (item, qty, unit)
    r = s.iloc[0]
    assert (r["min"], r["p25"], r["median"], r["p75"], r["quantity"], r["auctions"]) == (100, 200, 200, 200, 4, 2)

def test_bid_only_counts_quantity_not_price():
    s = summarise(to_frame(fetched(items=[item_auction(1, 10, 2, bid=50)])))
    assert s.iloc[0]["quantity"] == 2 and pd.isna(s.iloc[0]["median"])

def test_house_totals():
    assert house_totals(frame_of([(10, 2, 100), (20, 1, 5)])) == {"auctions": 2, "units": 3, "gold_listed": 205}
```

- [ ] **Steps 2–5:** Run (FAIL), implement, run (4 passed), commit `Hourly: listings frame and weighted summary`.

### Task 1.2: Sales estimate from two snapshots

**Files:**
- Create: `coppertrail/collector/sales.py`
- Test: `tests/test_sales.py`

**Interfaces:**
- Produces:
  - `MAX_SPAN_HOURS = 6`
  - `compare(prev: pd.DataFrame | None, cur: pd.DataFrame, prev_at: datetime | None, cur_at: datetime) -> pd.DataFrame`, with columns `item_id, gone_units, partial_units, short_gone_units, new_units, span_hours`, one row per item in `cur ∪ prev`.
    - When there is no prev, or the span is outside `(0, MAX_SPAN_HOURS]`, all of these columns are NULL.
    - `gone_units` = the quantity of auctions in prev that are missing in cur and were not `SHORT`. `short_gone_units` is the same for `SHORT`. `partial_units` = the positive quantity drop of auctions in both. `new_units` = the quantity of auctions that are new in cur.
  - `sold_value(prev, cur) -> int`: copper, the sum of `unit × (gone non-SHORT quantity + partial drop)`, with NaN units counted as 0.
  - State file: `save_state(path: Path, frame, observed_at, house: int)` and `load_state(path, house, now, copied_days) -> tuple[pd.DataFrame, datetime] | None`. The file is Parquet holding `auction_id, item_id, quantity, time_left, unit`, with metadata `observed_at` and `house`. `load_state` deletes and ignores the file when its house differs or its age exceeds `copied_days`.

- [ ] **Step 1: Write the failing tests**

```python
def test_gone_short_partial_new():
    prev = frame_of_ids([(1, 10, 5, "LONG"), (2, 10, 3, "SHORT"), (3, 10, 4, "MEDIUM"), (4, 20, 9, "LONG")])
    cur = frame_of_ids([(3, 10, 1, "MEDIUM"), (4, 20, 9, "LONG"), (5, 20, 2, "VERY_LONG")])
    r = compare(prev, cur, T0, T0 + timedelta(hours=1)).set_index("item_id")
    assert r.loc[10, ["gone_units", "short_gone_units", "partial_units", "new_units"]].tolist() == [5, 3, 3, 0]
    assert r.loc[20, ["gone_units", "new_units"]].tolist() == [0, 2] and r.loc[10, "span_hours"] == 1.0

def test_two_hour_span_kept(): ...            # span_hours == 2.0, values present
def test_no_prev_or_too_old_is_null():        # Review Focus 3
    assert compare(None, cur, None, T0)["gone_units"].isna().all()
    assert compare(prev, cur, T0, T0 + timedelta(hours=7))["span_hours"].isna().all()
def test_state_other_house_ignored(tmp_path): ...   # load_state(..., house=110) -> None and file deleted
def test_state_older_than_copied_days_deleted(tmp_path): ...
def test_sold_value(): ...                     # 5×unit of auction 1 + 3×unit of auction 3
```

- [ ] **Steps 2–5:** Run (FAIL), implement, run (6 passed), commit `Hourly: sales estimate and listings state`.

### Task 1.3: Selection rules (first-run selection)

**Files:**
- Create: `coppertrail/collector/selection.py`
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: `Selection` config, the `ITEMS` frame (window).
- Produces:
  - `passes(detail: dict | None, median: int | None, sel: Selection) -> str | None`. It returns `"rule"`, `"unclassified"` or None.
    - Unknown (`None` or `found=False`): `"unclassified"` if `include_unclassified`, else None.
    - Excluded: a quality in `exclude_qualities`; a class in `exclude_classes`; a class in `equipment_classes` below `equipment_min_quality`; `min_median` for that quality when the median is None or below it.
  - `build_selection(summary: pd.DataFrame, details: pd.DataFrame, traded: pd.Series | None, sel: Selection, previous: set[int], day: date) -> pd.DataFrame`, in the `SELECTION` schema.
    - The cap only applies when there are more candidates than `max_items`. Rank by `traded` (gold) descending.
    - A previous member stays while its rank is within `keep_rank`. Fill the rest by rank up to `max_items`.
  - `current_selection(store) -> set[int] | None`: the latest `SELECTION` file.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("detail,median,expected", [
    (d(quality="POOR"), 500, None),
    (d(quality="COMMON"), 49, None), (d(quality="COMMON"), 50, "rule"), (d(quality="COMMON"), None, None),
    (d(quality="UNCOMMON", cls="Recipe"), 9000, None),
    (d(quality="RARE", cls="Armor"), 9000, None), (d(quality="EPIC", cls="Weapon"), 9000, "rule"),
    (d(quality="UNCOMMON", cls="Consumable"), 1, "rule"),
    (None, 10, "unclassified"),
])
def test_passes(detail, median, expected):
    assert passes(detail, median, Selection()) == expected

def test_cap_ranks_by_traded_and_keeps_members(): ...   # max_items=2, keep_rank=3: previous member at rank 3 stays
def test_no_cap_below_max(): ...                         # all candidates, rank NULL
```

- [ ] **Steps 2–5:** Run (FAIL), implement, run (11 passed), commit `Selection rules and cap`.

### Task 1.4: Hourly run

**Files:**
- Replace the stub: `coppertrail/collector/hourly.py`
- Delete: `coppertrail/collector/legacy/{api,parse,watchlist,gaps,run}.py` and their tests (`test_run.py`, `test_parse_watchlist.py` with its 3-row price-table fixture, `test_collector_master_data.py`). `legacy/{store,config}.py` stay until WP3 no longer imports them.
- Test: `tests/test_hourly_run.py`

**Interfaces:**
- Consumes: Tasks 0.1–0.5, 1.1–1.3. Item lookups for unknown ids call `coppertrail.collector.master.refresh_items(client, store, ids, now)` (WP2, Task 2.1). Until WP2 is merged, the tests patch it.
- Produces: `main(cfg: Config, client: BlizzardClient | None = None, now: Callable[[], datetime] = utcnow, sleep=time.sleep) -> int`. The steps:
  1. Take the lock (`<data>/.lock`).
  2. Check `house_name()` contains `expect_house_name`, else exit 1.
  3. `since` = the `observed_at` of the newest `HOURLY` file.
  4. `listings(since)`. On None, poll every 60 s for up to 5 minutes, then exit 0 with "not modified".
  5. Look up unknown items (at most 500 per run, the rest next hour).
  6. Selection = `current_selection()`, or `build_selection()` on the first run.
  7. Summary plus `compare()`, filtered to the selection. Write `HOURLY` and `HOUSE` for the hour.
  8. `save_state()`.
  9. Call `client.static_namespace()`. When it differs from the newest `BUILDS` row, write a row with version and build parsed from it (`static-1.60.1_70399-forever-eu` gives `"1.60.1"` and `70399`) and `first_seen = observed_at`.

  Git is not touched here; the workflow commits.

- [ ] **Step 1: Write the failing tests** (mock transport, tmp data dir)

```python
def test_first_run_writes_hour_without_sales(tmp_path): ...      # HOURLY rows, gone_units NULL, state saved
def test_second_run_writes_sales(tmp_path): ...                  # span_hours 1.0
def test_not_modified_exits_0_and_writes_nothing(tmp_path): ...  # 304 six times; sleep called 5 times with 60
def test_same_snapshot_twice_is_idempotent(tmp_path): ...        # Review Focus 2: second main() writes no file, exit 0
def test_wrong_house_name_exits_1(tmp_path): ...
def test_only_selected_items_written(tmp_path): ...              # a POOR item is in house totals, not in HOURLY
def test_build_parsed_from_namespace(): assert parse_namespace("static-1.60.1_70399-forever-eu") == ("1.60.1", 70399)
```

- [ ] **Steps 2–5:** Run (FAIL), implement, run (7 passed), then the full suite with `uv run pytest -q` (green) and `uv run ruff check .`.
- [ ] **Step 6:** Live smoke test (needs Jack's `blizzard.toml` on this PC): `uv run python -m coppertrail.collector --data-dir %TEMP%\ct-smoke hourly`. Expected: exit 0, one `hourly/<day>/<HH>.parquet` with about 1,600 rows.
- [ ] **Step 7:** Commit `Hourly run on the Blizzard API; old collector removed`. Merge into `dev`.

---

## WP2: Master data and nightly run (session B)

### Task 2.1: Item details and recipes

**Files:**
- Create: `coppertrail/collector/master.py`
- Test: `tests/test_master.py`

**Interfaces:**
- Consumes: `BlizzardClient.item`, `BlizzardClient.json`, `Store`, `ITEMS`, `RECIPES`.
- Produces:
  - `refresh_items(client, store, ids: Iterable[int], now: datetime) -> int`. It looks up the ids and appends rows (including `found=False` for unknown ids) to today's `ITEMS` file in the window, merged with what's already there. Returns the count.
  - `known_items(store) -> pd.DataFrame`: the newest row per `item_id` across the window files.
  - `stale_items(store, now, max_age_days=7, retry_unfound_days=1) -> list[int]`
  - `refresh_recipes(client, store, now) -> int`. It walks profession index → profession → skill tiers → categories → recipes → recipe, skipping professions whose name contains `[DNT]`. It writes one `RECIPES` file for today: one row per reagent; a recipe without reagents gets one row with NULL reagent.

- [ ] **Step 1: Write the failing tests**

```python
def test_refresh_items_maps_fields(tmp_path): ...       # quality/class/subclass/sell_price/namespace from item_detail()
def test_unknown_item_stored_as_not_found(tmp_path): ...
def test_newest_row_wins(tmp_path): ...
def test_stale_items(tmp_path): ...                      # 8-day-old row and 2-day-old unfound row are stale
def test_recipes_walk_skips_dnt(tmp_path): ...           # 2 professions, one "[DNT]"; reagent rows match
```

- [ ] **Steps 2–5:** Run (FAIL), implement, run (5 passed), commit `Master data: item details and recipes from Blizzard`.

### Task 2.2: Window branch rebuild

**Files:**
- Create: `coppertrail/collector/window.py`
- Test: `tests/test_window.py` (temporary git repos via `subprocess`, skipped when git is missing)

**Interfaces:**
- Produces:
  - `prune_window(store, today: date, copied_days: int) -> list[Path]`. It collapses `ITEMS` into a single `items/<today>.parquet` (the newest row per item, dropping items with `fetched_at` older than `copied_days`). It keeps only the newest `RECIPES` file, if it is younger than `copied_days`. It deletes the older files and returns the deleted paths.
  - `rebuild_branch(window_dir: Path, message: str) -> str`. Inside the window worktree it creates an orphan commit of the current tree (`git checkout --orphan tmp`, `add -A`, `commit`, `branch -M window`) and returns the new sha. Pushing is the workflow's job.
  - `prune_summaries(store, today, summary_retention_days) -> list[Path]`: a no-op for 0.

- [ ] **Step 1: Write the failing tests**

```python
def test_prune_window_keeps_newest_items_within_days(tmp_path): ...
def test_rebuild_branch_leaves_single_commit(tmp_path):
    sha = rebuild_branch(repo, "window 2026-11-19")
    assert git(repo, "rev-list", "--count", "HEAD") == "1"
    assert old_file_blob_sha not in git(repo, "rev-list", "--objects", "--all")
def test_prune_summaries_zero_keeps_all(tmp_path): ...
def test_prune_summaries_30_deletes_older_hour_dirs(tmp_path): ...
```

- [ ] **Steps 2–5:** Run (FAIL), implement, run (4 passed), commit `Window branch: prune and single-commit rebuild`.

### Task 2.3: Nightly run

**Files:**
- Replace the stub: `coppertrail/collector/nightly.py`
- Test: `tests/test_nightly_run.py`

**Interfaces:**
- Consumes: Tasks 1.3, 2.1 and 2.2, plus `load_state` (Task 1.2) for the full latest listings.
- Produces: `main(cfg, client=None, now=utcnow) -> int`. The steps:
  1. Take the lock.
  2. Build the selection from the state listings: `summarise` → `passes` against `known_items`. `traded` = the sum of `sold_est × median` per item over the `HOURLY` rows of the last `rank_days`. Write `SELECTION` for today.
  3. `refresh_items(stale_items(...))`, at most 3,000 per night.
  4. On Mondays (UTC), or when no `RECIPES` file exists, run `refresh_recipes`.
  5. `prune_summaries`, then `prune_window`.
  6. `rebuild_branch(cfg.window_dir, f"window {today}")`.

  Exit 0, or 1 on error. With no state yet: skip step 2, still do the rest.

- [ ] **Step 1:** Write failing tests:
  - `test_nightly_writes_selection_and_rebuilds`;
  - `test_nightly_without_state_skips_selection`;
  - `test_recipes_only_on_monday_or_missing`.
- [ ] **Steps 2–5:** Run (FAIL), implement, run (3 passed), then the full suite. Commit `Nightly run: selection, master data, window rebuild`. Merge into `dev`.

---

## WP3: Query layer, patterns, GUI data (session C)

### Task 3.1: Series on the new tables

**Files:**
- Rewrite: `coppertrail/query/series.py`
- Test: `tests/test_query_series.py` (rewritten), plus a new `tests/new_archive.py` fixture builder: `make_archive(tmp_path, items: list[tuple], hours: dict[int, list[dict]]) -> Path`. It writes `HOURLY`, `HOUSE`, `ITEMS`, `RECIPES`, `BUILDS` and `SELECTION` through `Store`.

**Interfaces:**
- Consumes: `Store`, `TABLES` (Task 0.4). The window dir is `data_dir / "window"`.
- Produces (same calling style as today, tz-aware UTC, typed empty frames):
  - `hourly(data_dir, item_ids=None, start=None, end=None)`: the `HOURLY` columns.
  - `house(data_dir, start=None, end=None)`
  - `items(data_dir)`: `item_id, name, quality, item_class, subclass, required_level, vendor_price` (= `sell_price`). The newest row per item. Items without a row get the name `#<id>`.
  - `item_details(data_dir)` (kept for the pattern Context; same columns as today).
  - `recipes(data_dir)`: the columns the spreads pattern uses today (`recipe_id, name, profession, result_id, result_qty, reagent_id, reagent_qty`), mapped from `RECIPES`.
  - `builds(data_dir, start=None, end=None)`
  - `latest_per_item(data_dir, item_ids=None) -> pd.DataFrame`, with columns `item_id, observed_at, median, min_buyout, quantity, median_7d, median_30d, low_30d, high_30d, sales_per_day`:
    - from the latest hour per item, over the last 30 days of `HOURLY`;
    - `sales_per_day` = `sum(gone_units + partial_units)` over the last 7 days ÷ the covered days, where covered = hours with non-NULL `span_hours` ÷ 24;
    - NULL when nothing is covered.
  - `scans`, `snapshots`, `latest_snapshot` and `economy` are removed.

- [ ] **Step 1: Write the failing tests**

```python
def test_hourly_reads_hour_files_in_range(tmp_path): ...
def test_items_newest_row_and_placeholder_name(tmp_path): ...
def test_latest_per_item_sales_per_day(tmp_path):
    # 48 covered hours, 2 units sold each hour -> 48 units per day
    assert latest.loc[10, "sales_per_day"] == 48.0
def test_latest_per_item_medians(tmp_path): ...   # median_7d = median of hourly medians in the last 7 days
def test_missing_tables_give_typed_empty_frames(tmp_path): ...
```

- [ ] **Steps 2–5:** Run (FAIL), implement, run (5 passed), commit `Query: series on hourly, house and window tables`.

### Task 3.2: Pattern Context and jobs

**Files:**
- Modify: `coppertrail/patterns/base.py` (Context), `common.py` and every job that reads `ctx.snapshot`, `ctx.scans` or `ctx.economy`: `baseline, buyouts, correlations, inflation, mispricings, progression, reversion, rhythm, spreads, supply, vendor, weekday`.
- Modify: `tests/pattern_fixtures.py`, every `tests/test_pattern_*.py`, `tests/test_patterns_base.py`, `tests/test_patterns_baseline.py`.

**Interfaces:**
- Produces:
  - `Context.latest` (replaces `snapshot`, built from `series.latest_per_item`).
  - `Context.house` (replaces `economy`).
  - `Context.scans` is removed. The jobs that used it read `ctx.hourly` and use `observed_at` as the scan time, since there is one row per snapshot now.
  - `Context.hourly`, `items`, `details`, `recipes`, `builds` and `hourly_of` keep their names.
  - `common.sales_per_day(ctx)` reads `ctx.latest`.
  - `inflation` drops population; its gold-listed series is `house.gold_listed`.
  - Pattern keys, numbers, titles, `min_days` and `EVENT_COLS` stay unchanged.

- [ ] **Step 1:** Update `pattern_fixtures.py`: `snapshot_frame` becomes `latest_frame(sales: dict[int, float])` with the `latest_per_item` columns; `scans_frame` becomes rows of `hourly_frame`. Change each test to the new fixtures while keeping its assertions on ranked rows and events.
- [ ] **Step 2:** Run `uv run pytest tests/test_pattern_*.py tests/test_patterns_*.py -q`. Expected: FAIL (`Context` has no `latest`).
- [ ] **Step 3:** Change `Context` and the jobs.
- [ ] **Step 4:** Run the same command. Expected: all pass. Then run `uv run python -m coppertrail.patterns list`. Expected: 12 jobs.
- [ ] **Step 5:** Commit `Patterns on Blizzard tables: latest, house, hourly scans`.

### Task 3.3: GUI data code

**Files:**
- Modify: `coppertrail/query/catalog.py`, `coppertrail/ui/bridge.py`, `coppertrail/ui/viewdata.py`, `coppertrail/ui/movers.py`, `coppertrail/ui/patternview.py` (only where it reads removed fields).
- Modify: `tests/conftest.py` (`archive` fixture onto `new_archive.make_archive`), `tests/test_bridge*.py`, `tests/test_ui_movers.py`, `tests/test_ui_patterns.py`, `tests/test_query_tables.py`.

**Interfaces:**
- Consumes: Task 3.1, plus `format.CREDIT_TEXT` / `format.CREDIT_URL` (WP4 Task 4.1; if WP4 is not merged yet, add the two constants with the exact values from Task 4.1).
- Produces:
  - `catalog.archive_status(data_dir) -> ArchiveStatus` with `first_hour, last_hour, hours, missing_hours_7d, stale` (stale = last hour older than 3 h).
  - Archive-cutoff fields are removed.
  - The bridge state has `creditText` and `creditUrl` from `format`. The old source's URL constant is removed. The economy panels read `house`. Movers read `hourly`.

- [ ] **Step 1:** Rewrite the fixture and the GUI tests against the new archive. The bridge test asserts `state["creditText"] == CREDIT_TEXT` and no key containing `cutoff`.
- [ ] **Step 2:** Run `uv run pytest tests/test_bridge*.py tests/test_ui_*.py tests/test_query_*.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite (green) and `uv run python -m coppertrail.ui --screenshot %TEMP%\ct.png --sample`. Expected: an image is written.
- [ ] **Step 5:** Check that `git grep -n "collector.legacy" -- coppertrail tests` prints nothing. Commit `GUI data on the Blizzard tables`. Merge into `dev`.

---

## WP4: GUI chrome, pull, README (session D)

### Task 4.1: Credit and states

**Files:**
- Modify: `coppertrail/ui/format.py`, `coppertrail/ui/app.py` (the credit link opens `CREDIT_URL`), `coppertrail/ui/web/js/statusstrip.js`, `coppertrail/ui/web/js/states.js`, `coppertrail/ui/web/i18n/*.json` if they hold the strings.
- Test: `tests/test_ui_format.py`, `tests/test_app.py`

**Interfaces:**
- Produces:
  - `CREDIT_TEXT = "Data: Blizzard Entertainment API · not affiliated with or endorsed by Blizzard"`
  - `CREDIT_URL = "https://github.com/Jacklog-dev/Coppertrail#data-and-privacy"`
  - `statusstrip.js` shows `state.creditText` (fallback before the first state: the same text from i18n), linked to `state.creditUrl`.
  - `states.js`: the first-pull text becomes "Coppertrail keeps a local copy of your Blizzard auction archive. Pull once to start." The cutoff state is removed.

- [ ] **Step 1:** Write failing tests:
  - `test_credit_constants`: exact strings;
  - in `test_app.py`: the credit opens `CREDIT_URL`.
- [ ] **Steps 2–5:** Run (FAIL), implement, run (pass), run `uv run pytest tests/test_web_offline.py -q` (pass), commit `GUI credit: Blizzard as the data source`.

### Task 4.2: Pull for main and window

**Files:**
- Modify: `coppertrail/ui/pull.py`
- Test: `tests/test_pull.py` (temporary git repos: a bare origin with `main` and an orphan `window`)

**Interfaces:**
- Produces: `run_pull(data_dir, git="git", timeout=300) -> PullResult`, the same type as today. The steps:
  1. `git -C data pull --ff-only`.
  2. If `origin/window` exists after `git fetch origin window`:
     - when `data/window` is missing, `git worktree add --detach window origin/window`;
     - otherwise `git -C data/window reset --hard origin/window`;
     - then `git -C data worktree prune` and `git -C data gc --prune=now --quiet`.
  3. Any failure gives `PullResult(False, ...)` as today, with no exception.

- [ ] **Step 1: Write the failing tests**

```python
def test_pull_creates_window_worktree(tmp_path): ...
def test_pull_after_window_force_push(tmp_path):       # Review Focus 5
    # origin/window rewritten to a new orphan commit -> pull ok, window/ has only the new files
def test_pull_without_window_branch_still_pulls_main(tmp_path): ...
def test_main_not_fast_forward_reports_failure(tmp_path): ...
```

- [ ] **Steps 2–5:** Run (FAIL), implement, run (4 passed), commit `Pull: main fast-forward plus window worktree reset`.

### Task 4.3: README data and privacy section

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** Replace the old credit and data text with a `## Data and privacy` section (the anchor must match `CREDIT_URL`). It says:
  - Data comes from the Blizzard Entertainment API and is provided "as is".
  - Coppertrail is not affiliated with or endorsed by Blizzard.
  - The repo ships no data.
  - Data copied unchanged from Blizzard is kept for at most 30 days.
  - Coppertrail's own hourly conclusions are kept longer.
  - Nothing is collected about users.
  - GitHub may keep unreachable git objects for a while after the daily rewrite.
- [ ] **Step 2:** Check: `git grep -n "Data and privacy" README.md` prints one heading.
- [ ] **Step 3:** Commit `README: data and privacy`. Merge into `dev`.

---

## WP6: Handover scrub (session E, outside git)

### Task 6.1: Scrubbed handover copy

**Files:**
- Create: `private-next/handover/` (gitignored in the public repo), copied from `private/handover/` without `baseline-2026-11-17.md`.

- [ ] **Step 1:** Copy the folder, then delete `baseline-2026-11-17.md`.
- [ ] **Step 2:** In `HANDOVER.md`, `README.md` and the mockups (HTML and SVG text), make these changes:
  - Replace every passage about the old source with the Blizzard facts from the spec's "Verified API facts" section, or delete the passage.
  - Delete section 5's numbers (they were computed from the old data). Keep the definitions.
  - Change the status-strip credit in the mockups to `CREDIT_TEXT` (Task 4.1).
- [ ] **Step 3:** Check: a case-insensitive search of `private-next/handover` for the old source's name finds nothing.
- [ ] **Step 4:** Report the list of changed files and sections. There's no commit, because this folder is not in git yet.

---

## WP5: Workflows and the new data repo (this session, after WP1, WP2, WP6)

### Task 5.1: Data repo content

**Files (in `private-next/`, a fresh `git init -b main`):**
- `collector.toml`: the spec's `[blizzard]`, `[selection]` and `[retention]` blocks, verbatim.
- `.gitignore`: `window/`, `.state/`, `.lock`, `logs/`, `*.duckdb`.
- `README.md`: one line on what the repo holds, plus the credit.
- `handover/` from WP6.
- `.github/workflows/hourly.yml`:
  - `cron: "35 * * * *"` plus `workflow_dispatch`; `concurrency: {group: data, cancel-in-progress: false}`; `timeout-minutes: 30`.
  - Steps:
    1. Check out this repo (main) into `data/`.
    2. `git -C data fetch origin window`; `git -C data worktree add -B window window origin/window`, or create an empty orphan `window` on the first run.
    3. Check out `Jacklog-dev/Coppertrail` at `dev` into `code/`.
    4. `astral-sh/setup-uv`; `uv sync --no-dev` in `code/`.
    5. `actions/cache` restore of `data/.state`, key `listings-${{ github.run_id }}`, restore-keys `listings-`.
    6. `uv run python -m coppertrail.collector --data-dir ../data hourly`, with env `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET` from secrets.
    7. Commit and push `window` (if changed), then `main` (if changed), each with the rebase-and-retry loop from the old `collect.yml`.
    8. Save the cache.
  - No artifact upload.
- `.github/workflows/nightly.yml`:
  - `cron: "50 0 * * *"`, same concurrency group.
  - The same setup, then `... nightly`, then push `main` normally and `git -C data push --force origin window`.

- [ ] **Step 1:** Write the files. Validate both workflows with `uvx --from actionlint-py actionlint private-next/.github/workflows/*.yml`. Expected: no output.
- [ ] **Step 2:** Run the hourly command once locally against `private-next/` (with Jack's local `blizzard.toml`). Expected: exit 0, hour files present, `window/` holds item details.

### Task 5.2: Replace the data repo (Jack confirms each step in chat)

- [ ] **Step 1:** Ask: "Delete `Jacklog-dev/Coppertrail_Database` on GitHub now? This cannot be undone by us; GitHub keeps a 90-day owner restore." Only on yes: `gh repo delete Jacklog-dev/Coppertrail_Database --yes`.
- [ ] **Step 2:** Ask: "Create the new private `Jacklog-dev/Coppertrail_Database` and push main?" On yes: `gh repo create Jacklog-dev/Coppertrail_Database --private`, then commit in `private-next/` and push main.
- [ ] **Step 3:** Jack sets the secrets himself: `gh secret set BLIZZARD_CLIENT_ID --repo Jacklog-dev/Coppertrail_Database` and the same for the secret.
- [ ] **Step 4:** Start the first run: `gh workflow run hourly.yml --repo Jacklog-dev/Coppertrail_Database`. Watch it with `gh run watch` (in the background). Expected: success, one commit on main and a `window` branch.
- [ ] **Step 5:** Check that `gh run view --log` holds no price values or secrets: `gh run view <id> --log | grep -E "unit_price|buyout|client_secret"` prints nothing.

---

## WP7: Purge and final check (this session, last)

### Task 7.1: No trace in the tree

**Files:**
- Create: `tests/test_no_old_source.py`. It runs `git ls-files` and asserts that no tracked file's text contains `"ah" + "ledger"` (case-insensitive). The term is built from parts so the test doesn't match itself.
- Modify or delete what it finds:
  - `CLAUDE.md` (rewrite the sections on API facts, repos and the collector for Blizzard);
  - `CHANGELOG.md` (restart under `## 0.0.1 [Core]` with only current-state bullets);
  - the own-scans research note (delete);
  - older specs and plans under `docs/superpowers/` (delete the ones about the old collector; scrub the rest);
  - this plan and its spec (replace the search term with "the old source");
  - the probe and snapshot scripts in `scripts/` (delete; the collector supersedes them);
  - `packaging/`, `.github/workflows/build-exe.yml`, `scripts/build_exe.py`, `pyproject.toml`, `coppertrail/__init__.py`.
- Delete: the `coppertrail/collector/legacy/` package.

- [ ] **Step 1:** Add the test. Run it. Expected: FAIL, listing the files.
- [ ] **Step 2:** Fix every listed file. Run `uv run pytest -q` and `uv run ruff check .`. Expected: all green, including the new test.
- [ ] **Step 3:** Commit `Remove the old data source from the tree`. Merge into `dev`.

### Task 7.2: History rewrite and local cleanup (Jack confirms each step in chat)

- [ ] **Step 1:** Ask: "Replace the public repo's whole history with one new commit of the current tree, force-push `main` and `dev`, and delete all `claude/*` branches and worktrees?" On yes:
  - `git checkout --orphan fresh && git commit -m "Coppertrail" && git branch -f main fresh && git branch -f dev fresh`
  - `git push --force origin main dev`
  - remove each `claude/*` worktree and branch, locally and on origin
  - `git reflog expire --expire=now --all && git gc --prune=now`
- [ ] **Step 2:** Check: `git log --all --oneline | wc -l` prints 1, and `git rev-list --all --objects | git cat-file --batch-check | wc -l` matches a fresh clone.
- [ ] **Step 3:** Ask: "Delete the old `private/` clone, `data/`, `build/` and `dist/` on this PC, then clone the new data repo into `private/`?" On yes, do it, and then move `private-next/handover` into place if it isn't already pushed.
- [ ] **Step 4:** Update the memory: delete the old archive-cutoff memory and its index line; add a `project` memory on the Blizzard source, house 111 and the 30-day rule with Jack's reading.
- [ ] **Step 5:** Tell Jack what is left for him: old session transcripts under `~/.claude`, the `wow-forever-ah-check` skill, and the 90-day GitHub restore window.

### Task 7.3: End-to-end check

- [ ] **Step 1:** After two scheduled hourly runs, pull in the GUI (`uv run python -m coppertrail.ui --data-dir private`). Expected: a data age under 2 h, item names shown, the credit text visible.
- [ ] **Step 2:** `uv run python -m coppertrail.patterns run spreads`. Expected: a basis line with 1 day (most jobs report `needs_days`, which is correct this early).
- [ ] **Step 3:** After the first nightly run: `git -C private/window log --oneline | wc -l` prints 1.
