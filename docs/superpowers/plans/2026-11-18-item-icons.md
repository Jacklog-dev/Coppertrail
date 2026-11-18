# Item Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real item icons beside item names in the GUI, loaded by URL from Blizzard's render host, with no key needed at runtime.

**Architecture:** A dev script builds `coppertrail/ui/web/data/icons.json` (item id -> icon file id) once from the media API. `coppertrail/ui/icons.py` turns ids into URLs; the bridge exposes `icons()`; `js/itemicon.js` caches the map and draws `<img>` or a fallback square.

**Tech Stack:** Python 3.12, httpx (existing `BlizzardClient`), plain ES modules.

**Spec:** `docs/superpowers/specs/2026-11-18-item-icons-design.md`

## Global Constraints

- URL: `https://render.worldofwarcraft.com/eu/icons/56/<file_data_id>.jpg`; the host appears only in Python and the CSP, never in JS/CSS.
- CSP in every page: `img-src 'self' data: https://render.worldofwarcraft.com`.
- No icon fetching in `collector/` hourly/nightly code; no image files in git or the exe.
- No hex colours or font names outside tokens; sizes come from `tokens.py` (regenerate `tokens.css`).
- Never log credentials or the token.

## Review Focus

- Offline or blocked image: fallback square, no broken-image glyph (`error` handler swaps it).
- Item with no map entry (unknown to Blizzard): fallback square, never a request.
- Missing or corrupt `icons.json` (fresh checkout, bad edit): `icon_url` returns None, app still starts.
- Script rerun after a patch: existing entries kept, new ones added, a failed lookup does not drop an entry.
- Frozen exe: `icons.json` found through `devserver.web_dir()`.

---

### Task 1: Icon map module and fetch script

**Files:** Create `coppertrail/ui/icons.py`, `scripts/fetch_icon_map.py`, `tests/test_icons.py`; add a `media_icon` method to `coppertrail/collector/blizzard.py` (source-specific code stays there).

**Interfaces:**
- Produces: `icons.ICON_URL = "https://render.worldofwarcraft.com/eu/icons/56/{}.jpg"`, `icons.load_map(path: Path | None = None) -> dict[int, int]` (cached on default path; `{}` on missing/bad file), `icons.icon_url(item_id: int, m: dict[int,int] | None = None) -> str | None`.
- Produces: `BlizzardClient.media_icon(item_id: int) -> int | None` (static namespace then fallback; asset `key == "icon"` -> `file_data_id`).
- Produces: `scripts/fetch_icon_map.py`: `merge(old: dict[int,int], new: dict[int, int | None]) -> dict[int,int]`, `write_map(path, m)` (sorted keys, JSON object of str -> int), `main(argv)` with `--data-dir`, `--out`, `--workers 4`.

- [ ] Tests: `test_icon_url_builds_render_url` (`icon_url(2453, {2453: 134181})` endswith `/eu/icons/56/134181.jpg`), `test_icon_url_none_without_entry`, `test_load_map_missing_or_bad_file_is_empty`, `test_merge_keeps_old_and_ignores_none`, `test_media_icon_reads_file_data_id` (mock transport, like `test_blizzard_client.py`), `test_shipped_map_is_valid` (if file exists: all keys/values positive ints).
- [ ] Run, see fail; implement; run, see pass.
- [ ] Run the script against `private-next` with Jack's credentials; commit `icons.json`.
- [ ] Commit.

### Task 2: Bridge `icons()`

**Files:** Modify `coppertrail/ui/bridge.py` (`EXPOSED`, new method), test in `tests/test_bridge.py`.

**Interfaces:** `Bridge.icons() -> dict[str, str]`: `{str(item_id): url}` for catalog items that have an entry.

- [ ] Test `test_icons_maps_catalog_items_to_urls` (monkeypatch `icons.load_map`); fail; implement; pass; commit.

### Task 3: Front end

**Files:** Create `web/js/itemicon.js`; modify `main.js` (load once before first render), `overview.js`, `itemdetail.js` (list rows and header), `movers.js`, `patterns.js` (+ `patternview.item_cell` etc. gain `"id"`), `groupeditor.js`; CSS in `components.css`; tokens `iconItem` 18, `iconItemLarge` 40 in `tokens.py`; CSP in `index.html`, `sample.html`.

**Interfaces:** `loadIcons(): Promise<void>`, `itemIcon(id: number, large = false): HTMLElement` (`img.item-icon` with `loading=lazy`, `alt=""`, `error` -> fallback `span.item-icon.none`).

- [ ] Test `test_pages_allow_render_host_images_only` in `test_web_offline.py`; `test_patterns` payload item cells carry `id`.
- [ ] Implement, regenerate tokens, run `uv run pytest -q`, `ruff check`, screenshot via `--dev` with `COPPERTRAIL_CONFIG` set to a scratch folder.
- [ ] Update CLAUDE.md / HANDOVER 8b wording; commit.
