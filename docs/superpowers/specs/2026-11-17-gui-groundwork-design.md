# GUI groundwork: states, breakpoints, chart blocks

Date: 2026-11-17. Scope: `coppertrail/ui/` and its tests only (session that owns `ui/` in
`docs/superpowers/plans/2026-11-17-complete-the-app.md`). Source of truth: HANDOVER 8b
"States", "Resizing", "Charts in uPlot" and the mock-ups `States`, `Overview1280`,
`OverviewUltrawide`, `ItemDetail`, `Movers`.

## States (`web/js/states.js`, `web/css/states.css`)

Each state is a function returning a DOM node; the bridge supplies every display string.

| State | Trigger in the app | Bridge payload |
|---|---|---|
| No data yet | `status.empty` and no load error | `dataDir`, `status` |
| Data stale | `status.stale` | `status.banner {title, detail}`, `status.lastPoint` (unix s), `status.noDataSince` |
| Filter matches nothing | `items.shown == 0` and `items.total > 0` | `noMatch {sub, chips [{label, clear}], hint {label, count} or null}` |
| Loading | first `state` call, data-folder change | text only, optional percent (indeterminate bar without one) |
| Pull failed | a failed pull with a reason other than "not a clone" | `pullFailure {title, cause, reassurance, request, log}` |
| Too little history | patterns (later) | `Bridge.history_gap(needed_days, have_days, ready_on, unit)` |

- Stale: banner at the top of the view (dismissable for that `as_of`), status strip in
  `attention` with the clock icon, charts shade the area after `lastPoint` (`staleTail`
  plugin in `charts.js`, label "no data since 13 Nov 07:55").
- Filter matches nothing: one chip per active *item* filter (the date range never drops
  items, so it gets no chip). The hint names the single filter whose removal brings back
  the most items ("without Min sales/day ≥ 5,000 → 38 items"); none when no single filter
  helps. Chip x sends that filter's default via `set_filters`.
- Pull failed replaces the view content until the user picks a view, retries or the next
  pull succeeds. "Show log" expands git's output. The request line is
  `git pull --ff-only · exit 1 · 08:44:10` in mono `text3` (git instead of the mock-up's
  HTTP line: the GUI's only network action is a git pull).
- Loading has no real progress source yet (loads are synchronous); the bar runs
  indeterminate unless a percent is passed. The component is ready for pattern loads.

## Breakpoints (`frame.css`, `filterbar.css`, `layout.css`, `js/layout.js`)

`tokens.BREAKPOINTS = {"compact_max": 1440, "ultrawide_min": 2400}`; CSS media queries and
`layout.js` use the same numbers (a test compares them).

- ≤ 1440 px: nav rail 56 px (icons only, CSS tooltips from `data-tip`), view padding 16,
  Class / date button / Min sales fold into a "More" button whose badge counts the active
  folded filters (button `active` when > 0). The More popover lists the three controls;
  each opens its usual popover anchored on More. Layout helpers collapse to one column.
- ≥ 2400 px: `.tiles` shows 6 tiles (`.tile-extra` appear), `.with-aside` gains its third
  column (`.aside`); `layout.breakpoint()` and an `onBreakpoint` listener for JS that
  needs to know.

## Chart blocks (`web/js/charts.js`)

- `lineChart` gains: `sync` key (linked cursor and zoom across charts with the same key,
  matching x range and y-axis width), `bands [[upper, lower, colour]]` at 12 %,
  `refLines [{value, label}]`, `markers [{t, kind, label}]` (diamond `s4` mispricing,
  square `s3` supply shock, down-triangle `s2` buyout, dotted drop line, drawn in a `draw`
  hook), `stale {from, to, label}`.
- `barChart`: `uPlot.paths.bars` with the 28 % gap, optional highlighted bars in a
  second colour (supply shocks in `s3`).
- `chartCard({title, sub, legend, build})`: card header with legend and a reset-zoom
  button; reset applies to the whole sync group.
- `sparkline(values, dir)`: 96×26 SVG polyline in `rise`/`fall` with an end dot.
- `rangeBar({low, high, usual, current})`: 140 px SVG, typical range `borderStrong`, usual
  tick `text2`, current price as a `s4` diamond. SVG rather than uPlot: it lives in table
  cells, one uPlot instance per row would be heavy.
- Tooltip keeps flipping left near the right edge of the plot.

The style sample (`--sample`) shows every chart block and every state with invented values.
