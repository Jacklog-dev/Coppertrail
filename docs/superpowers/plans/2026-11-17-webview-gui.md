# pywebview GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the PySide6 GUI with a pywebview window rendering plain HTML/CSS/JS, back at the 6.2 level (theme, nav rail, filter bar, group editor, status strip, four placeholder views).

**Architecture:** A Qt-free Python `Bridge` wraps `coppertrail.query` and returns JSON-able dicts. In the app, JS reaches it through pywebview's `js_api`; with `--dev`/`--screenshot` it goes through a 127.0.0.1-only stdlib HTTP server that wraps the same `Bridge`. The page is plain ES modules with no build step, styled from a `tokens.css` generated from `tokens.py`. Charts use vendored uPlot.

**Tech Stack:** Python 3.12, pywebview ≥ 5.3 (EdgeChromium on Windows, GTK on Linux, Cocoa on macOS), stdlib `http.server`, uPlot 1.6.31 (vendored), headless Edge for screenshots, pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-webview-gui-design.md` (read it first), plus HANDOVER 8a/8b in `private/handover/HANDOVER.md` and the mock-ups in `private/handover/mockups-html/` (visual source of truth; numbers in them are invented).

## Global Constraints

- No Qt anywhere: no PySide/PyQt/qtpy/pyqtgraph/QtWebEngine, and never `gui="qt"` in pywebview. `uv.lock` must contain none of them (Task 1 test).
- No Node/npm, no bundler, no front-end framework. Plain ES modules (`<script type="module">`).
- Nothing loads from the internet at runtime: fonts via local `@font-face`, uPlot vendored. The mock-ups pull Google Fonts; do not copy those `<link>`s.
- All colours, fonts and sizes come from `web/css/tokens.css` variables (generated from `coppertrail/ui/tokens.py`). No hex colours or font names in `components.css`/JS except inside `tokens.css`.
- Almendra only for h1 and card titles: `text-transform: uppercase; letter-spacing: .06em`. Everything else Caudex. Numeric columns Caudex 400 with `font-variant-numeric: tabular-nums`.
- One 1 px border per panel, 4 px card radius. No shadows, gradients, ornaments, textures.
- Copper (`--accent`) only for selected/primary/links/changed filters. Coin colours only for price marks.
- Rise/fall always ▲/▼ plus sign with a real minus (−); strings come from `coppertrail/ui/format.py`.
- JS puts data strings into the DOM with `textContent` (never `innerHTML` with data). Item names come from the API.
- The GUI's only network action is "Pull latest data" (`git -C <data_dir> pull --ff-only`). The only external link is the AHledger credit (`https://ahledger.com`), opened in the system browser.
- The AHledger credit "Prices from AHledger" is visible in the status strip at all times.
- `uv sync --no-dev` must not install GUI deps: pywebview stays in the `gui` extra.
- Downloading uPlot needs Jack's explicit OK in chat (state file names, source, size) before the download.
- Code, comments and UI copy in English. Ruff clean (`uv run ruff check .`, `uv run ruff format .`).

## Review Focus

1. **Stale archive (> 2 days old):** status strip says "Data is N days old · as of …" with the stale flag set, not "Data as of …". Test in Task 3.
2. **Empty or brand-new data folder:** the app opens, shows "No data yet", 0 items, Pull disabled with a reason, and no exception. Test in Task 3.
3. **Pull failures:** a folder that is not a git clone, or a missing `git`, returns a failure message and leaves the archive untouched; it never raises into the UI thread. Tests in Task 3.
4. **Dev server exposure:** it binds 127.0.0.1 only, serves nothing outside `web/` (`/../pyproject.toml` → 404) and calls only listed bridge methods (`/api/_x`, `/api/__init__` → 404). Tests in Task 4.
5. **Group renamed or deleted while selected in the filter:** the selection follows the rename and drops a deleted name, and the saved settings match. Test in Task 3.

---

## File structure (end state)

```
coppertrail/ui/
  __init__.py, __main__.py      entry point (calls app.main)
  tokens.py, format.py          unchanged
  webtheme.py                   tokens.py -> web/css/tokens.css (+ CLI)
  bridge.py                     Bridge: all GUI data, Qt-free, no pywebview import
  pull.py                       run_pull(): git pull --ff-only
  devserver.py                  127.0.0.1 HTTP server: static web/ + POST /api/<method>
  screenshot.py                 headless Edge command
  app.py                        pywebview window, AppApi(Bridge), CLI
  web/
    index.html, sample.html
    fonts/  (moved from ui/fonts)   icons/ (moved from ui/icons)
    vendor/uPlot.esm.js, uPlot.min.css, uPlot-LICENSE
    css/tokens.css (generated), base.css, components.css
    js/api.js, dom.js, coins.js, charts.js, icons.js,
       main.js, navrail.js, statusstrip.js, views.js, filterbar.js, popover.js,
       calendar.js, groupeditor.js, sample.js
tests/
  test_no_qt.py, test_webtheme.py, test_bridge.py, test_pull.py,
  test_devserver.py, test_app.py, test_web_offline.py, test_ui_format.py (unchanged)
```

---

### Task 1: Remove Qt

**Files:**
- Delete: `coppertrail/ui/{charts,controls,filterbar,groupeditor,sample,theme,widgets,window}.py`, `coppertrail/ui/theme.qss`, `tests/test_ui_theme.py`, `tests/test_ui_window.py`
- Move: `coppertrail/ui/fonts/` → `coppertrail/ui/web/fonts/`, `coppertrail/ui/icons/` → `coppertrail/ui/web/icons/` (`git mv`)
- Modify: `pyproject.toml` (`gui` extra), `uv.lock`, `coppertrail/ui/__main__.py`, `coppertrail/ui/format.py` (docstring and MONTHS comment mention Qt)
- Test: `tests/test_no_qt.py`

**Interfaces:**
- Produces: `coppertrail/ui/web/fonts/*.ttf`, `coppertrail/ui/web/icons/*.svg` at their new paths; `python -m coppertrail.ui` exists but prints "GUI is being rebuilt" and returns 1 until Task 5.

- [ ] **Step 1: Write the failing test** `tests/test_no_qt.py`

```python
QT_PACKAGES = {"pyside6", "pyside6-essentials", "pyside6-addons", "shiboken6",
               "pyqt5", "pyqt6", "qtpy", "pyqtgraph", "pyqt6-webengine"}

def test_lock_file_has_no_qt():
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    names = {p["name"].lower() for p in lock["package"]}
    assert not names & QT_PACKAGES

def test_no_qt_imports_in_package():
    for py in Path("coppertrail").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+(PySide|PyQt|qtpy|pyqtgraph)", text, re.M), py
```

- [ ] **Step 2: Run it:** `uv run pytest tests/test_no_qt.py -q` → FAIL (PySide6 in lock, Qt imports present).
- [ ] **Step 3: Delete and move the files listed above.** In `pyproject.toml` set `gui = ["pywebview>=5.3"]` (no extras). Replace `__main__.py` with a stub that prints `GUI is being rebuilt (pywebview), see docs/superpowers/plans/2026-11-17-webview-gui.md` to stderr and returns 1. In `format.py` drop "without Qt" wording and change the MONTHS comment to "strftime month names follow the process locale".
- [ ] **Step 4: `uv lock && uv sync`**, then `uv run pytest -q` → all pass (including `test_no_qt.py`); `uv run ruff check .` → clean. Check `uv.lock` for `qtpy`: pywebview must not have pulled it in.
- [ ] **Step 5: Commit** `git add -A coppertrail tests pyproject.toml uv.lock docs && git commit -m "GUI: remove the Qt implementation (switching to pywebview)"` (includes the design doc and this plan)

---

### Task 2: tokens.css generator

**Files:**
- Create: `coppertrail/ui/webtheme.py`, `coppertrail/ui/web/css/tokens.css` (generated)
- Test: `tests/test_webtheme.py`

**Interfaces:**
- Produces: `tokens_css() -> str`, `TOKENS_CSS: Path` (= `web/css/tokens.css`), CLI `python -m coppertrail.ui.webtheme` (writes the file). CSS variable names that later tasks use:
  - every `DARK` key as `--<key>` (e.g. `--bg0`, `--accent`, `--borderStrong`, `--goldRing`)
  - per `TYPE` role `r`: `--type-r-family` (quoted family + fallback `, "Segoe UI Symbol", serif`), `--type-r-weight`, `--type-r-size` (px), `--type-r-transform` (`uppercase`/`none`), `--type-r-spacing` (`.06em` / `.01em` / `0`)
  - `--space-1` … `--space-7` (px), `--radius-<key>`, `--size-<key>` with snake_case → kebab (`--size-nav-w`, `--size-control-h`), `--coin-mark`, `--coin-gap`, `--coin-ring` (px)
  - chart values: `--chart-line-primary` (unitless), `--chart-area-alpha`, `--chart-band-alpha`, `--chart-bar-gap`, `--chart-axis-font` (px), `--chart-marker-dot` (px)
  - a `:root[data-theme="light"]` block with the `LIGHT` colours (unused now, keeps the switch possible)

- [ ] **Step 1: Write the failing tests**

```python
def test_committed_tokens_css_is_current():
    assert TOKENS_CSS.read_text(encoding="utf-8") == tokens_css(), \
        "run: uv run python -m coppertrail.ui.webtheme"

def test_every_colour_is_a_variable():
    css = tokens_css()
    for key, value in tokens.DARK.items():
        assert f"--{key}: {value};" in css

def test_type_and_sizes():
    css = tokens_css()
    assert '--type-h1-family: "Almendra", "Segoe UI Symbol", serif;' in css
    assert "--type-h1-transform: uppercase;" in css and "--type-h1-spacing: .06em;" in css
    assert "--type-body-size: 14px;" in css and "--size-nav-w: 200px;" in css
    assert "--space-5: 24px;" in css and "--coin-mark: 7px;" in css

def test_light_block():
    assert ':root[data-theme="light"]' in tokens_css()
```

- [ ] **Step 2: Run:** `uv run pytest tests/test_webtheme.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `tokens_css()` from `tokens.DARK/LIGHT/TYPE/SPACE/RADIUS/SIZES/CHART/COIN` (output order follows the dicts, header comment "Generated from coppertrail/ui/tokens.py, do not edit"), and the `__main__` block writing `TOKENS_CSS`. Run the CLI once to create the file.
- [ ] **Step 4: Run:** `uv run pytest tests/test_webtheme.py -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "GUI: generate tokens.css from tokens.py"` (both files plus test).

---

### Task 3: Bridge and pull

**Files:**
- Create: `coppertrail/ui/bridge.py`, `coppertrail/ui/pull.py`
- Test: `tests/test_bridge.py`, `tests/test_pull.py` (use the `archive` and `config_dir` fixtures from `tests/conftest.py`)

**Interfaces:**
- Consumes: `coppertrail.query` (`load_items`, `archive_status`, `default_data_dir`, `apply_filters`, `item_classes`, `date_window`, `load_groups`, `save_groups`, `load_settings`, `save_settings`, `Filters`, `ItemGroup`), `coppertrail.ui.format`.
- Produces:
  - `pull.py`: `@dataclass PullResult(ok: bool, message: str, detail: str = "")`; `can_pull(data_dir: Path) -> bool` (`(data_dir / ".git").exists()`); `run_pull(data_dir: Path, git: str = "git", timeout: float = 300) -> PullResult`. Messages are exact: success `"Pulled latest data"`, git exit ≠ 0 `"Pull failed · the local archive is unchanged"` (detail = combined output), git not startable `"Pull failed · git could not be started"`, not a clone `"The data folder is not a git clone"`.
  - `bridge.py`: `STALE_AFTER_DAYS = 2`, `PREVIEW_ROWS = 300`, `AHLEDGER_URL = "https://ahledger.com"`, and

    ```python
    class Bridge:
        EXPOSED: ClassVar[tuple[str, ...]] = (
            "state", "set_filters", "reset_filters", "save_groups",
            "group_members", "search_items", "match_names", "set_data_dir", "pull_latest")
        def __init__(self, data_dir: Path | None = None, *, now: Callable[[], datetime] | None = None): ...
        def state(self) -> dict: ...
        def set_filters(self, filters: dict) -> dict: ...        # saves settings, returns state()
        def reset_filters(self) -> dict: ...
        def save_groups(self, groups: list[dict], renamed: dict[str, str] | None = None) -> dict: ...
        def group_members(self, group: dict) -> list[dict]: ...  # ItemRow list, name order
        def search_items(self, text: str, group: dict) -> dict:  # {"rows": [ItemRow ≤ 50], "note": "4 results not yet in group"}
        def match_names(self, names: list[str]) -> dict: ...     # {"ids": [...], "missing": int, "note": "1 pasted name not found" | ""}
        def set_data_dir(self, path: str) -> dict: ...           # saves Settings.data_dir, reloads, returns state()
        def pull_latest(self) -> dict: ...                       # {"ok", "message", "detail"}; reloads on success
    ```
    `data_dir` passed to `__init__` is a session override: it is never written to settings.
  - `state()` payload (camelCase keys, everything preformatted):

    ```
    {"dataDir": str, "status": {"text": str, "stale": bool, "empty": bool, "canPull": bool, "pullHint": str},
     "creditUrl": AHLEDGER_URL,
     "filters": Filters.to_json(), "active": [labels], "activeLabel": "No filters" | "1 filter active" | "3 filters active",
     "classes": [str], "groups": [GroupDict + "count": int], "groupsLabel": "All groups" | "Leather chain, Herbs",
     "groupsSummary": "2 of 6 selected · 6 items", "minSalesPass": "3 of 9 items pass",
     "window": {"from": iso, "to": iso, "label": "9 Nov – 16 Nov 2026", "archiveFrom": iso|None, "archiveTo": iso|None},
     "items": {"shown": int, "total": int, "sub": "9 of 9 items", "rows": [ItemRow ≤ PREVIEW_ROWS]}}
    GroupDict = {"name", "itemIds", "patterns", "excludedIds"}
    ItemRow   = {"id": int, "name": str, "class": str, "price": Coin | None, "salesPerDay": "25,000"}
    Coin      = {"parts": [[12, "g"], [67, "s"]], "text": "12g 67s"}
    ```
    `save_groups` ignores extra keys such as `count` on incoming group dicts. A missing data folder must not raise anywhere in the bridge.
    `groupsSummary` counts the union of the selected groups' members over all items (no selection: all items, "0 of 6 selected · 9 items"). `minSalesPass` counts items with `sales_per_day >= min_sales`, ignoring the other filters.

- [ ] **Step 1: Write the failing tests.** `tests/test_bridge.py` (fixed `now = 2026-11-16 09:00 UTC` unless stated):

```python
def test_state_loads_archive(archive, config_dir):
    s = Bridge(archive, now=NOW).state()
    assert s["items"]["sub"] == "9 of 9 items"
    assert s["activeLabel"] == "No filters"
    assert s["window"]["label"] == "9 Nov – 16 Nov 2026"
    assert s["status"]["text"] == "Data as of 16 Nov 2026, 08:00" and not s["status"]["stale"]
    assert s["status"]["canPull"] is False and s["status"]["pullHint"] == "The data folder is not a git clone"
    row = next(r for r in s["items"]["rows"] if r["name"] == "Rugged Leather")
    assert row["price"] == {"parts": [[14, "s"], [95, "c"]], "text": "14s 95c"}

def test_filters_apply_and_persist(archive, config_dir):
    b = Bridge(archive, now=NOW)
    s = b.set_filters({"groups": ["Leather chain"], "min_sales": 50})
    assert s["items"]["sub"] == "2 of 9 items" and s["activeLabel"] == "2 filters active"
    assert load_settings().filters.groups == ["Leather chain"]
    assert b.reset_filters()["items"]["sub"] == "9 of 9 items"
    assert load_settings().filters == Filters()

def test_data_dir_override_not_saved(archive, config_dir):
    Bridge(archive, now=NOW).set_filters({"min_sales": 10})
    assert load_settings().data_dir == ""

def test_popover_counts(archive, config_dir):
    s = Bridge(archive, now=NOW).set_filters({"groups": ["Leather chain", "Herbs"], "min_sales": 50})
    assert s["groupsSummary"] == "2 of 6 selected · 6 items"
    assert s["minSalesPass"] == "3 of 9 items pass"
    assert s["groupsLabel"] == "Leather chain, Herbs"

def test_custom_range_any_order(archive, config_dir):
    s = Bridge(archive, now=NOW).set_filters(
        {"range": "custom", "date_from": "2026-11-12", "date_to": "2026-11-10"})
    assert s["window"]["label"] == "10 Nov – 12 Nov 2026"

def test_stale_archive(archive, config_dir):                       # Review Focus 1
    s = Bridge(archive, now=lambda: datetime(2026, 11, 19, 9, tzinfo=UTC)).state()
    assert s["status"]["stale"] and s["status"]["text"].startswith("Data is 3 days old · as of ")

def test_empty_folder(tmp_path, config_dir):                       # Review Focus 2
    s = Bridge(tmp_path / "nothing", now=NOW).state()
    assert s["status"]["empty"] and s["status"]["text"] == "No data yet"
    assert s["items"]["total"] == 0 and s["status"]["canPull"] is False

def test_group_rename_and_delete_follow_selection(archive, config_dir):   # Review Focus 5
    b = Bridge(archive, now=NOW)
    b.set_filters({"groups": ["Herbs", "Cloth"]})
    groups = [g for g in b.state()["groups"] if g["name"] != "Cloth"]
    for g in groups:
        if g["name"] == "Herbs":
            g["name"] = "Flowers"
    s = b.save_groups(groups, renamed={"Herbs": "Flowers"})
    assert s["filters"]["groups"] == ["Flowers"]
    assert load_settings().filters.groups == ["Flowers"]
    assert [g.name for g in load_groups()] == [g["name"] for g in groups]

def test_group_editor_helpers(archive, config_dir):
    b = Bridge(archive, now=NOW)
    leather = next(g for g in b.state()["groups"] if g["name"] == "Leather chain")
    assert len(b.group_members(leather)) == 4
    found = b.search_items("potion", leather)
    assert [r["name"] for r in found["rows"]] == ["Superior Healing Potion"]
    assert found["note"] == "1 result not yet in group"
    m = b.match_names(["Peacebloom", "No Such Item", "black lotus"])
    assert sorted(m["ids"]) == [2447, 13468] and m["note"] == "1 pasted name not found"
```

`tests/test_pull.py` (Review Focus 3):

```python
def test_not_a_clone(tmp_path):
    r = run_pull(tmp_path)
    assert not r.ok and r.message == "The data folder is not a git clone"

def test_git_missing(tmp_path):
    (tmp_path / ".git").mkdir()
    r = run_pull(tmp_path, git="no-such-git-binary")
    assert not r.ok and r.message == "Pull failed · git could not be started"

def test_pull_from_local_remote(tmp_path):
    # bare origin + clone A (pusher) + clone B (data dir), all via subprocess git, no network
    ...  # A commits a file and pushes; run_pull(B) -> ok, file now exists in B
    assert r.ok and r.message == "Pulled latest data"

def test_failed_pull_keeps_archive(tmp_path):
    # clone B whose origin was deleted -> git exits non-zero
    assert not r.ok and r.message == "Pull failed · the local archive is unchanged" and r.detail
```

- [ ] **Step 2: Run:** `uv run pytest tests/test_bridge.py tests/test_pull.py -q` → FAIL (modules missing).
- [ ] **Step 3: Implement `pull.py`**: `subprocess.run([git, "-C", str(data_dir), "pull", "--ff-only"], capture_output=True, text=True, timeout=timeout)`; `OSError`/`TimeoutExpired` → "could not be started" (timeout detail "git timed out").
- [ ] **Step 4: Implement `bridge.py`.** Port the logic of the deleted Qt `window.py` / `filterbar.py` / `groupeditor.py` (git history, commit `ef1502b`) for status text, plurals ("1 item", "2 items"), paste matching (case-insensitive exact name) and search (case-insensitive substring, items not in the group, name order). `set_filters` builds `Filters.from_json({**current.to_json(), **changes})`. `save_groups` maps renamed names in `filters.groups`, drops names that no longer exist, saves both files. Keep the loaded items/groups/status in the instance; reload on `set_data_dir` and on a successful pull.
- [ ] **Step 5: Run:** `uv run pytest tests/test_bridge.py tests/test_pull.py -q` → PASS; `uv run ruff check .` → clean.
- [ ] **Step 6: Commit** `git commit -m "GUI: Qt-free bridge and git pull for the web front end"`

---

### Task 4: Dev server and api.js

**Files:**
- Create: `coppertrail/ui/devserver.py`, `coppertrail/ui/web/js/api.js`
- Test: `tests/test_devserver.py`

**Interfaces:**
- Consumes: `Bridge`, `Bridge.EXPOSED`.
- Produces:
  - `WEB_DIR: Path` (= `coppertrail/ui/web`); `serve(bridge: Bridge, port: int = 0) -> tuple[ThreadingHTTPServer, str]` (returns the started server, running in a daemon thread, and its base URL `http://127.0.0.1:<port>/`). `GET` serves files under `WEB_DIR` only; `POST /api/<name>` with body `{"args": [...]}` returns `{"result": ...}` for names in `Bridge.EXPOSED`, 404 otherwise, 500 `{"error": str}` on exceptions. JSON uses `ensure_ascii=False`, UTF-8.
  - `api.js`: `export async function call(name, ...args)`. It uses `window.pywebview.api[name](...args)` when `window.pywebview` exists (awaits the `pywebviewready` event if the api is not attached yet), otherwise `fetch("/api/" + name, {method: "POST", body: JSON.stringify({args})})`. Also `export function on(event, fn)`; `window.ct = { emit(event, payload) }` dispatches to those listeners (Python pushes events with `evaluate_js("ct.emit(...)")`).

- [ ] **Step 1: Write the failing tests** (Review Focus 4)

```python
def test_serves_index_and_api(archive, config_dir):
    srv, url = serve(Bridge(archive))
    try:
        assert url.startswith("http://127.0.0.1:")
        assert srv.server_address[0] == "127.0.0.1"
        assert urlopen(url + "js/api.js").status == 200
        body = post(url + "api/state", {"args": []})
        assert body["result"]["items"]["total"] == 9
    finally:
        srv.shutdown()

@pytest.mark.parametrize("path", ["../pyproject.toml", "..%2F..%2Fpyproject.toml", "%2e%2e/bridge.py"])
def test_no_files_outside_web(archive, config_dir, path):
    ...  # GET url + path -> HTTPError 404

@pytest.mark.parametrize("name", ["_reload", "__init__", "EXPOSED", "nope"])
def test_only_exposed_methods(archive, config_dir, name):
    ...  # POST url + "api/" + name -> HTTPError 404
```

- [ ] **Step 2: Run:** `uv run pytest tests/test_devserver.py -q` → FAIL.
- [ ] **Step 3: Implement** with `http.server.ThreadingHTTPServer` and a `BaseHTTPRequestHandler`. Resolve paths with `(WEB_DIR / unquote(path)).resolve()` and require `is_relative_to(WEB_DIR.resolve())`. Content types for `.html .js .css .svg .ttf .json` (`.js` → `text/javascript`). Silence request logging. Write `api.js` as specified.
- [ ] **Step 4: Run:** `uv run pytest tests/test_devserver.py -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "GUI: localhost dev server and JS api transport"`

---

### Task 5: App window, CLI and screenshots

**Files:**
- Create: `coppertrail/ui/app.py`, `coppertrail/ui/screenshot.py`, minimal `coppertrail/ui/web/index.html` (title, links `css/tokens.css`, a "Coppertrail" text and `<script type="module" src="js/main.js">`; `main.js` calls `api.call("state")` and writes `items.sub` into the page)
- Modify: `coppertrail/ui/__main__.py` (calls `app.main`)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `Bridge`, `serve`, `WEB_DIR`, `run_pull`.
- Produces:
  - `app.py`: `gui_backend(platform: str = sys.platform) -> str | None` (`"win32"` → `"edgechromium"`, `"linux"` → `"gtk"`, else `None`); `class AppApi(Bridge)` adding `pick_data_folder() -> dict` (pywebview `FOLDER_DIALOG`; returns `state()` or unchanged state on cancel), `open_credit() -> None` (`webbrowser.open(AHLEDGER_URL)`, no other URL) and an overridden `pull_latest()` that starts a worker thread and returns `{"started": True}`. The thread emits `ct.emit("pull", {"ok", "message", "detail", "state"})`. `AppApi.EXPOSED = Bridge.EXPOSED + ("pick_data_folder", "open_credit")`. `main(argv: list[str] | None = None) -> int` with `--data-dir DIR`, `--size WxH` (default `1600x1000`, screenshot default `1920x1080`), `--screenshot PNG`, `--dev` (start the dev server, print the URL, open the system browser, block until Ctrl+C), `--sample` (open `sample.html` instead of `index.html`; combinable with `--dev`/`--screenshot`).
  - The window: `webview.create_window("Coppertrail", str(WEB_DIR / page), js_api=AppApi(...), width, height, min_size=(1280, 720), background_color=tokens.DARK["bg1"])`, `webview.start(gui=gui_backend(), http_server=True)`.
  - `screenshot.py`: `find_edge() -> Path | None` (Program Files (x86) and Program Files `Microsoft/Edge/Application/msedge.exe`, then `shutil.which("msedge")`); `edge_command(edge: Path, url: str, out: Path, size: tuple[int, int]) -> list[str]` = `[edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}", "--virtual-time-budget=5000", f"--screenshot={out}", url]`; `take(url: str, out: Path, size: tuple[int, int]) -> int` (runs it, returns exit code; prints `wrote <out>`).

- [ ] **Step 1: Write the failing tests**

```python
def test_backend_never_qt():
    assert gui_backend("win32") == "edgechromium"
    assert gui_backend("linux") == "gtk"
    assert gui_backend("darwin") is None

def test_edge_command(tmp_path):
    cmd = edge_command(Path("msedge.exe"), "http://127.0.0.1:1/", tmp_path / "a.png", (1920, 1080))
    assert "--window-size=1920,1080" in cmd and f"--screenshot={tmp_path / 'a.png'}" in cmd
    assert cmd[-1] == "http://127.0.0.1:1/"

def test_app_api_exposes_extra_methods():
    assert {"pick_data_folder", "open_credit"} <= set(AppApi.EXPOSED)
    assert set(Bridge.EXPOSED) <= set(AppApi.EXPOSED)

def test_open_credit_only_opens_ahledger(monkeypatch, archive, config_dir):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    AppApi(archive).open_credit()
    assert opened == ["https://ahledger.com"]
```

- [ ] **Step 2: Run:** `uv run pytest tests/test_app.py -q` → FAIL.
- [ ] **Step 3: Implement** `screenshot.py` and `app.py` as specified. `--screenshot` runs `serve(...)`, then `take(url + page, out, size)`, then shuts the server down and returns the Edge exit code (1 with the message `Microsoft Edge not found` when `find_edge()` is None). The dev server wraps a plain `Bridge` (no dialog, synchronous pull).
- [ ] **Step 4: Run:** `uv run pytest -q` → PASS. Then `uv run python -m coppertrail.ui --data-dir private --screenshot shot.png` → `wrote shot.png`; the image shows "N of N items". Then `uv run python -m coppertrail.ui` opens a native window with the same text. Close it. Delete `shot.png`.
- [ ] **Step 5: Commit** `git commit -m "GUI: pywebview window, CLI, dev mode and headless Edge screenshots"`

---

### Task 6: Theme CSS, coins, charts and style sample (checkpoint)

**Files:**
- Create: `web/css/base.css`, `web/css/components.css`, `web/js/dom.js`, `web/js/coins.js`, `web/js/icons.js`, `web/js/charts.js`, `web/sample.html`, `web/js/sample.js`, `web/vendor/uPlot.esm.js`, `web/vendor/uPlot.min.css`, `web/vendor/uPlot-LICENSE`
- Test: `tests/test_web_offline.py`

**Interfaces:**
- Produces (used by Tasks 7 to 9 and later views):
  - `base.css`: the `@font-face` rules (Caudex 400/700 normal/italic, Almendra 400/700) with `url("../fonts/…ttf")`; body in `--bg1`, `--text1`, Caudex body type, `font-variant-numeric: tabular-nums`; scrollbars (8 px, thumb `--scroll`); `a` in `--accent`.
  - `components.css` classes: `.card`, `.card-title` (title type, uppercase via the variables), `.h1`, `.sub`, `.btn`, `.btn.primary`, `.btn.ghost`, `.btn.link`, `.ctl` + `.ctl.active` (filterActive look), `.seg` (+ `button[aria-pressed=true]`), `.input`, `.chip`, `.popover`, `.menu`, `.dialog` + `.backdrop`, `table.data` (36 px rows, `--grid` lines, `th` in th type and `--text3`, selected row `--accentMuted`), `.coin` with `i.g/i.s/i.c` marks (7 px circles in coin colour, 1 px ring via `box-shadow: inset`), `.up` / `.dn` (rise/fall colour), `.dot` (6 px circle), `.tooltip`. Values come from the mock-ups' CSS (`FilterBar.html`, `MarketOverview.html`), translated to the token variables.
  - `dom.js`: `el(tag, {class, text, attrs, on}, ...children) -> HTMLElement` (text via `textContent`).
  - `coins.js`: `coin(c: Coin | null) -> HTMLElement` (`—` for null); `change(text, direction) -> HTMLElement` (`.up`/`.dn` span with the given text); `axisCoins(copper: number) -> string`, the axis letter form only (`8g`, `1g 50s`, `80s`, `3,101g` from 100 gold; same rules as `format.coins_text`), the one formatter that lives in JS.
  - `icons.js`: `icon(name, size = 18) -> Promise<SVGElement>` (fetches `icons/<name>.svg` once, caches it, inlines it, strokes it with `currentColor`).
  - `charts.js`: `cssVar(name) -> string`; `lineChart(el, {x: number[] (unix seconds), series: [{label, color: "s1", width: "primary"|"secondary"|"tertiary", fill?: true}], refLine?: number, height: number}) -> uPlot`. It applies the CHART rules: horizontal grid only in `--grid`, axes in `--text3` at `--chart-axis-font`, dashed `[4,4]` `--text3` reference line, crosshair dashed `--text3`, 8 px hover dots with a 2 px `--surface` ring, a tooltip `.tooltip` that flips to the left near the right edge, drag-to-zoom and a `reset()` method on the returned chart.
  - `sample.html`: wordmark, h1 + card title, the type scale, every colour token swatch, a table with coin values (`12g 67s 5c`, `19s 8c`, `3,101g`), changes `▲ +14.2 %` / `▼ −87 %`, buttons/controls in all states, a segmented control, a chip, and one `lineChart` with two series plus the baseline 100. Sample values are hard-coded and invented.

- [ ] **Step 1: Ask Jack** in chat to OK downloading uPlot 1.6.31 from `https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/` (`uPlot.esm.js` ≈ 130 KB unminified, `uPlot.min.css` ≈ 2 KB) plus its MIT `LICENSE`. Wait for the yes, then download into `web/vendor/`.
- [ ] **Step 2: Write the failing test** `tests/test_web_offline.py`

```python
REMOTE = re.compile(r"""(src|href)\s*=\s*["']https?://|url\(\s*["']?https?://|@import\s+["']?https?://|from\s+["']https?://""", re.I)

def test_web_loads_nothing_remote():
    for f in WEB_DIR.rglob("*"):
        if f.suffix in {".html", ".css", ".js"} and "vendor" not in f.parts:
            assert not REMOTE.search(f.read_text(encoding="utf-8")), f

def test_no_hard_coded_colours_or_fonts_outside_tokens():
    for f in [*WEB_DIR.glob("css/*.css"), *WEB_DIR.glob("js/*.js")]:
        if f.name == "tokens.css":
            continue
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", text), f
        assert "Almendra" not in text or f.name == "base.css", f
        assert "Caudex" not in text or f.name == "base.css", f
```

- [ ] **Step 3: Run:** `uv run pytest tests/test_web_offline.py -q` → FAIL (no CSS yet or a violation), or PASS vacuously. Either way, continue.
- [ ] **Step 4: Implement** the files above. In `sample.html` add the CSP `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:">`; do the same in `index.html`.
- [ ] **Step 5: Run:** `uv run pytest -q` → PASS. `uv run python -m coppertrail.ui --sample --screenshot sample.png` → `wrote sample.png`. Check the PNG against `private/handover/mockups/` (Tokens board): Almendra uppercase titles, Caudex elsewhere, equal-width digits, ▲/▼ rendered (not tofu), coin marks round.
- [ ] **Step 6: Commit** `git commit -m "GUI: web theme, coins, uPlot charts and style sample"` (vendor files included).
- [ ] **Step 7: Checkpoint.** Send Jack `sample.png` (SendUserFile) and wait for his OK before Task 7. Delete `sample.png` from the repo folder afterwards (it is not committed).

---

### Task 7: Window frame: nav rail, status strip, placeholder views

**Files:**
- Modify: `web/index.html`, `web/js/main.js`
- Create: `web/js/navrail.js`, `web/js/statusstrip.js`, `web/js/views.js`

**Interfaces:**
- Consumes: `api.call`, `api.on`, `el`, `coin`, `icon`, the state payload from Task 3.
- Produces: `main.js` keeps one `state` object and exports `render(state)`, which calls `navrail.render`, `filterbar.render` (Task 8; until then a placeholder 64 px bar), `views.render` and `statusstrip.render`. Grid layout: nav `--size-nav-w` | main (filter bar `--size-filterbar-h` + scrolling view with `--size-view-pad` padding), status strip `--size-status-h` full width.
  - Nav: shield `icons/app.svg` 30 px + wordmark ("Copper" in `--accent`, "trail" in `--text1`, Caudex 700 17 px) in a 64 px header. Four buttons with icons overview/item/patterns/movers and labels Market overview, Item detail, Patterns, Movers & outliers (selected: `--accentMuted` background, `--accent` text, bold). "Data folder" button at the bottom calls `api.call("pick_data_folder")` (in dev mode it prompts for a path with `window.prompt` and calls `set_data_dir`).
  - Views: each placeholder shows h1 (view name), sub `state.items.sub` plus ` · ` plus `state.window.label`, and a `table.data` of `state.items.rows` (Item, Class, Lowest buyout (coin), Sales/day, right-aligned numbers).
  - Status strip: 6 px dot (`--rise` fresh, `--attention` stale, hidden when empty) + `status.text` (stale → `--attention`) · "Pull latest data" `.btn.link` with download icon (disabled with `title=pullHint` when `!canPull`; "Pulling…" while running; on the `pull` event shows the message for failures and re-renders with `payload.state` on success) · spacer · "Prices from AHledger" link with external icon calling `api.call("open_credit")` (dev mode: plain `<a target=_blank>`).

- [ ] **Step 1: Implement** the modules above, following `MarketOverview.html` for the nav rail and status strip measurements.
- [ ] **Step 2: Verify in dev mode:** `uv run python -m coppertrail.ui --data-dir private --dev`. In the browser pane: nav switches views (selected styling moves), the sub line reads "N of N items · <range>", the status strip shows the date and the AHledger credit. Pull is disabled with the hint when the folder has no `.git`.
- [ ] **Step 3: Verify the native window:** `uv run python -m coppertrail.ui`. The credit link opens the system browser and Data folder opens the native folder picker.
- [ ] **Step 4:** `uv run pytest -q` → PASS (offline/colour tests still hold). `uv run python -m coppertrail.ui --data-dir private --screenshot frame.png`; compare with `private/handover/mockups/` overview at 1920×1080 (frame only).
- [ ] **Step 5: Commit** `git commit -m "GUI: window frame, nav rail, status strip and placeholder views"`

---

### Task 8: Filter bar and popovers

**Files:**
- Create: `web/js/filterbar.js`, `web/js/popover.js`, `web/js/calendar.js`

**Interfaces:**
- Consumes: state fields `filters`, `active`, `activeLabel`, `classes`, `groups`, `groupsLabel`, `groupsSummary`, `minSalesPass`, `window`; `api.call("set_filters", partial)` and `api.call("reset_filters")`, both returning a new state for `main.render`.
- Produces:
  - `popover.js`: `openPopover(anchor: HTMLElement, content: HTMLElement, {onClose}) -> {close()}`, positioned under the anchor, flipped to stay inside the window, closed by Escape and by an outside click. One open at a time.
  - `calendar.js`: `calendar({from, to, min, max, onPick(lo, hi)}) -> HTMLElement`, a month grid with Monday first and English month names. Days outside `min..max` are disabled. Two clicks pick a range in either order.
  - `filterbar.js`: `render(container, state, onState)`. Controls in order, per HANDOVER 8b "Filter bar" and `FilterBar.html`:
    1. Groups `.ctl` showing `groupsLabel` (elided with CSS) plus a pencil button (opens the group editor, Task 9). Popover: search field, `groupsSummary`, All/None, checkable rows with `count`, footer "New group" and "Edit groups…".
    2. Class `.ctl` "Class: All classes" with a menu of `classes`.
    3. Search input (220 px, search icon, placeholder "Search items"), debounced 250 ms.
    4. `.seg` 24 h / 7 d / 30 d / All, none pressed for `custom`; date `.ctl` with calendar icon showing `window.label`. Popover: the same quick choices plus From/To fields and the calendar (`min/max` = `archiveFrom/archiveTo`).
    5. Min sales/day `.ctl`; popover with a number input (step 10, min 0), chips 0 / 10 / 50 / 200 / 1,000, and `minSalesPass`.
    6. Spacer, then `activeLabel` (`--accent` with a 6 px copper dot when anything is active, otherwise "No filters" in `--text3`) and a ghost "Reset".
  - Every control whose filter is in `state.active` gets `.active`.

- [ ] **Step 1: Implement** the three modules. Every change calls `set_filters` with only the changed keys and re-renders from the returned state.
- [ ] **Step 2: Verify in dev mode** against the fixture-like real data in the browser pane:
  - Select Leather chain: the sub line changes, Groups gets `.active`, the label reads "1 filter active".
  - Min sales 50: the popover shows "N of M items pass".
  - Calendar range 12 → 10 Nov: the date label reads "10 Nov – 12 Nov 2026" and no segment is pressed.
  - Reset: back to "No filters".
  - Reload the page: the filters are still set (persisted).
- [ ] **Step 3:** `uv run pytest -q` → PASS. Take a screenshot with a popover open (temporarily `?open=groups` handled in `main.js`, kept as a dev aid) and compare with `FilterBar.html`.
- [ ] **Step 4: Commit** `git commit -m "GUI: filter bar with groups, class, search, date and min sales popovers"`

---

### Task 9: Group editor

**Files:**
- Create: `web/js/groupeditor.js`

**Interfaces:**
- Consumes: `state.groups`, `api.call("group_members", group)`, `api.call("search_items", text, group)`, `api.call("match_names", names)`, `api.call("save_groups", groups, renamed)`.
- Produces: `openGroupEditor(state, {newGroup = false, onState})`. It opens a modal `.dialog` of about 1060×560 over a `.backdrop` and edits a deep copy of `state.groups`; nothing is saved until "Save groups". Three panes per HANDOVER 8b "Item-group editor":
  - **Groups** (240 px): drag-reorderable list (grip icon); New, Duplicate, Delete. New and Duplicate names are unique: base, then "base 2", "base 3".
  - **Members:** name input (tracks renames into the `renamed` map, chained renames collapse to the original name), "N items in this group", a table (Item, Class, Lowest buyout, remove ×). Remove calls the same rule as `ItemGroup.remove`: drop from `itemIds` and add to `excludedIds`. Pasting newline-separated names while the table area has focus calls `match_names`, adds the ids (removing them from `excludedIds`) and shows the `note`.
  - **Add items** (300 px): search field, `note`, checkable result rows with price, "Add N selected".
  - Footer: ghost Cancel (also Escape) and primary "Save groups".

- [ ] **Step 1: Implement** `groupeditor.js`, wired to the pencil button, "New group" (opens with a new group selected) and "Edit groups…".
- [ ] **Step 2: Verify in dev mode** in the browser pane:
  - Leather chain shows its members; remove one and the count drops.
  - Search "potion" shows results; tick one and the button reads "Add 1 selected"; add it.
  - Paste "Peacebloom\nNo Such Item\nblack lotus" into a new group: two members and "1 pasted name not found".
  - Cancel: nothing changes.
  - Rename Herbs to Flowers while it is selected in the filter, then save: the filter shows Flowers.
  - Delete a selected group and save: it leaves the filter.
- [ ] **Step 3:** `uv run pytest -q` → PASS; screenshot with the editor open, compare with the group-editor board in `FilterBar.html`.
- [ ] **Step 4: Commit** `git commit -m "GUI: item-group editor"`

---

### Task 10: Docs

**Files:**
- Modify: `CLAUDE.md`, `README.md` (if it mentions Qt/PySide), `private/handover/HANDOVER.md` (private repo)

- [ ] **Step 1: CLAUDE.md:**
  - Status: theme and frame exist on pywebview.
  - Commands: replace the GUI lines with `uv run python -m coppertrail.ui` (`--data-dir DIR`, `--dev`, `--sample`, `--screenshot PNG`, `--size WxH`) and `uv run python -m coppertrail.ui.webtheme` (regenerate tokens.css).
  - GUI notes: remove every Qt note (QSS, class fonts, `::item`, QCalendarWidget). Add notes on the bridge and transport, on the dev server being 127.0.0.1-only and dev/screenshot-only, on `tokens.css` being generated (the test fails when stale), on uPlot being vendored, and on JS writing data strings with `textContent`. Keep the Caudex Regular/Bold digit note and the ▲ ▼ fallback note (now: CSS font fallback).
  - Architecture stack line: "pywebview (WebView2) with HTML/CSS/JS and uPlot".
  - Design rules: "the QSS template" → "`tokens.css` and the CSS files".
- [ ] **Step 2: HANDOVER.md** (in `private/`):
  - 8a: the toolkit paragraph, with a pointer to the design doc.
  - 8b: "QSS approach" → "CSS approach" (tokens.css + classes); the Fonts and uppercase paragraphs in CSS terms; the Filter bar and group editor specs without Qt class names.
  - "Charts in pyqtgraph" → "Charts in uPlot", with the same rules (`cursor.sync` for linked x-axes, hooks for markers).
  - 9: note that 6.1 and 6.2 were redone on pywebview on 2026-11-17.

  Keep everything else verbatim.
- [ ] **Step 3: Verify:** `uv run pytest -q` and `uv run ruff check .` → clean. Search for leftover Qt mentions: Grep for `PySide|QSS|pyqtgraph|Qt ` in `CLAUDE.md`, `README.md` and `coppertrail/`. The only hits allowed are "no Qt" statements.
- [ ] **Step 4: Commit** the public repo (`git commit -m "Docs: GUI on pywebview"`), then commit in `private/` (`git -C private commit -am "Handover: GUI toolkit is pywebview + HTML (no Qt)"`). Do not push either without Jack's say-so.
