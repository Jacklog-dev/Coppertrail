# GUI on pywebview + HTML/CSS (replaces PySide6)

Date: 2026-11-17. Status: approved by Jack on 2026-11-17.

## Intent

Jack does not want Qt in his hobby apps (personal reasons, not up for discussion). The GUI built so far (HANDOVER 6.1 theme, 6.2 window frame) is PySide6 + pyqtgraph and must be replaced. Python stays: it is the right tool for the data work and pattern recognition. Only the GUI layer changes.

## Goals

- A native desktop window (HANDOVER 8a: "a real application window, not generated HTML pages") whose content is HTML/CSS/JS rendered by the OS web engine, driven by Python.
- Reach the same state the Qt GUI had: theme + style sample (6.1), window frame with nav rail, filter bar, group editor, status strip and four placeholder views (6.2). Then continue with 6.3 onward on the new stack.
- Match the mock-ups in `private/handover/mockups-html/` closely; they are HTML already, so their CSS is the starting point.
- Keep every HANDOVER 8a/8b rule: data only through the query layer, the only network action is "Pull latest data", tokens as the single source of colours/fonts/sizes, restraint rules, coin and percent conventions, AHledger credit always visible.

## Non-goals

- No change to the collector, the archive format, the query layer (`coppertrail/query/`), settings/groups storage, or the data repo workflow.
- No parchment (light) theme now (still "only if Jack asks").
- No web deployment, no remote access. The page is only ever served to this machine.

## Anti-goals (failure even if it works)

- **Any Qt**, directly or indirectly: no PySide/PyQt, no QtWebEngine, no pywebview Qt backend, no pyqtgraph.
- A Node/npm build chain or a front-end framework that brings its own look (Bootstrap, Material, Quasar, ...). The look comes from the tokens and the mock-ups only.
- Loading anything from the internet at runtime (CDNs, web fonts). Everything is vendored.
- A GUI that drifts from the mock-ups because "that's how the web component looks".

## Constraints

- Windows 11 is the main target; WebView2 ships with it. The code stays platform-neutral where cheap.
- pywebview pulls in `pythonnet` on Windows (for WebView2). That is fine; it has no Qt.
- The collector workflow runs `uv sync --no-dev` and must not install GUI deps (as today with the `gui` extra).
- Tests stay offline. HANDOVER design rules (CLAUDE.md "Design rules") still apply in review.

## Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| **pywebview + plain HTML/CSS/JS** | Reuses the HTML mock-ups almost directly; CSS does uppercase + letter spacing, tabular digits and glyph fallback natively; charts need a small JS library and some JS code | **Chosen by Jack** |
| Dear PyGui | Pure Python, excellent built-in charts (ImPlot), but ImGui look, no letter spacing, no font fallback (▲ ▼), no mixed fonts in one text item, slowing maintenance, hard to test headless | Rejected: fights the design |
| NiceGUI | Pure Python UI code, but its components carry Quasar's look; a second fight with the design | Rejected |

## Design

### Shape

```
python -m coppertrail.ui
  └─ pywebview window (gui="edgechromium" on Windows, "gtk" on Linux, cocoa on macOS; never qt)
       loads coppertrail/ui/web/index.html
       JS  ──api.call(name, args)──►  Bridge (Python, Qt-free)  ──►  coppertrail.query / pattern jobs
       JS  ◄──events (progress, pull done)── window.evaluate_js
```

### Python side (`coppertrail/ui/`)

- `bridge.py`: class `Bridge` with one public method per GUI need (`status()`, `catalog(filters)`, `groups()`, `save_groups(...)`, `settings()`, `save_filters(...)`, `pull_latest()`, later one method per view/pattern). Methods take and return plain JSON-able dicts/lists. No pywebview import in this module, so it is unit-testable with pytest against a fixture data dir (as `tests/conftest.py` does today).
- Formatting stays in Python: `format.py` (already Qt-free) produces display strings, and coin values are returned as structured parts (`{"g": 12, "s": 67, "c": 5}` or short form) so JS only paints marks. JS gets one small axis-tick formatter (`8g`, `1g 50s`, `80s`) because chart ticks are computed client-side.
- Long tasks (`git pull`, heavy loads) run in a worker thread; progress is pushed to JS as events (`window.evaluate_js("ct.emit('pull', {...})")`).
- `app.py` / `__main__.py`: creates the window, exposes the bridge (`js_api`), handles `--data-dir`, `--size`, `--screenshot`, `--dev`.
- `tokens.py` stays the single source. A generator writes `web/tokens.css` (CSS custom properties `--bg0`, `--accent`, `--type-h1-size`, ...); the file is committed and a test fails if it is out of date with `tokens.py`.

### Transport (my call)

JS never calls `window.pywebview.api` directly; it calls `api.call(name, args)` from `web/js/api.js`, which uses:

- the pywebview bridge when running in the app;
- otherwise `POST http://127.0.0.1:<port>/api/<name>` to a tiny stdlib HTTP server (`coppertrail/ui/devserver.py`) that wraps the same `Bridge`. Bound to 127.0.0.1 only, started only by `--dev` or `--screenshot`.

This gives three things from one code path: open the page in a normal browser with real data while building (`--dev`), screenshots without a visible window, and room for browser-driven tests later. A normal app start never starts the dev server; the window talks to Python only through the pywebview bridge.

### Screenshots (my call)

`--screenshot PNG [--size 1920x1080]` starts the dev server and runs headless Edge (`msedge --headless --screenshot=... --window-size=...`), which is on every Windows 11 machine. No extra download. Used for the "show Jack a screenshot before building views" checkpoints.

### Front end (`coppertrail/ui/web/`)

- Plain ES modules, no build step, no framework. `index.html`, `css/` (`tokens.css` generated, `base.css`, `components.css`), `js/` (one module per view plus `filterbar.js`, `groupeditor.js`, `charts.js`, `coins.js`, `api.js`).
- Fonts: the bundled `.ttf` files (already in `ui/fonts/`) via `@font-face`. Almendra only for h1 and card titles via `text-transform: uppercase; letter-spacing: .06em`. Numbers use Caudex 400 with `font-variant-numeric: tabular-nums` (Caudex Regular digits are already equal width; Bold is not, so numeric columns stay at 400).
- ▲ ▼ come from system font fallback (`font-family: Caudex, "Segoe UI Symbol", sans-serif`); coin marks and status dots are CSS circles, not glyphs.
- Icons: the existing SVGs in `ui/icons/`, inlined and coloured with `currentColor`.
- Popovers, date picker, calendar, segmented controls, spin box: hand-built from the FilterBar mock-up, not native `<input type=date>` (unstylable).
- A Content-Security-Policy in `index.html` allows only local resources.

### Charts (my call): uPlot

Vendored uPlot (MIT, ~50 KB, made for fast time series). It covers what HANDOVER 8b asks for: crosshair with custom tooltip, hover dots, horizontal grid only, dashed reference lines, area fills and bands between series, bars, linked cursors/x-scales across the two Item detail plots (`cursor.sync`), drag-to-zoom plus reset. Event markers and range bars are small custom draw hooks. The section "Charts in pyqtgraph" in HANDOVER 8b gets rewritten as "Charts in uPlot" with the same rules.

### What happens to the Qt code

Done as the first step (see Work order). Delete `charts.py`, `controls.py`, `filterbar.py`, `groupeditor.py`, `sample.py`, `theme.py`, `theme.qss`, `widgets.py`, `window.py` and the Qt tests (`test_ui_theme.py`, `test_ui_window.py`). Keep `tokens.py`, `format.py`, `fonts/`, `icons/`, `test_ui_format.py`. In `pyproject.toml` the `gui` extra becomes `pywebview` (Qt-free backends only). The style sample becomes `web/sample.html` (`python -m coppertrail.ui --sample`).

### Docs to update

- HANDOVER 8a (toolkit), 8b ("QSS approach" → "CSS approach", Fonts, uppercase, "Charts in pyqtgraph" → uPlot, Qt widget names in the filter bar and group editor specs → plain descriptions), 9 (step 6.1/6.2 redone on the new stack). The handover lives in the private repo; commit there.
- CLAUDE.md: Status, Commands (`--dev`, `--sample`), GUI notes (all Qt-specific notes go; add the pywebview/transport/tokens.css notes), Architecture stack line.

### Source of truth (my call)

HANDOVER 8b and the mock-ups define the look and behaviour. The Qt frame from 6.2 is not a reference; where it and the spec disagree, the spec wins. Behaviour the spec leaves open but the query layer already implements (filter persistence, group storage, archive clamping in `filtering.py`) carries over unchanged because it lives in `coppertrail/query/`. The old Qt code stays readable in git history (commit `ef1502b`) if a detail is needed.

### Work order

1. Remove Qt first: delete the Qt modules and tests listed above, drop PySide6 and pyqtgraph from `pyproject.toml` and the lock file, add `pywebview`. The app has no GUI for a short stretch; that is accepted.
2. Theme on the new stack: `tokens.css` generator + test, `sample.html` with fonts, tabular digits, colours, coins, ▲/▼, one uPlot chart. Screenshot to Jack before going on (same checkpoint as 6.1).
3. Window frame matching HANDOVER 8b and the mock-ups: nav rail, filter bar with all popovers and the group editor, status strip with credit and "Pull latest data", four placeholder views listing the filtered items. Bridge tests for every method used.
4. Update HANDOVER and CLAUDE.md, then continue with HANDOVER 6.3.

## Left to the builder

- Exact bridge method names and payload shapes; JS module split.
- How the dev server picks its port and how `api.js` learns it.
- Whether a JS test harness is worth adding once views hold logic (would need a JS runtime; ask before adding Node).
- Window chrome details (native title bar vs. frameless) — default: native title bar.
