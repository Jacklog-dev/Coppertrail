// The view states from HANDOVER 8b "States" (mock-up States.png). Each function returns a
// node; every data string comes from the bridge (bridge.py), only fixed copy lives here.
import { el, svg } from "./dom.js";
import { icon } from "./icons.js";

const centred = (cls, ...children) => el("div", { class: "state " + cls, attrs: { role: "status" } }, ...children);

// A: no data yet ---------------------------------------------------------------------

/** The small trail illustration: a dotted path from a copper ring to a trail mark. */
function trail() {
  return svg(
    "svg",
    { class: "trail", width: 200, height: 110, viewBox: "0 0 200 110", "aria-hidden": "true" },
    svg("path", { class: "dots", d: "M14 92 C 48 92, 52 54, 86 60 S 128 86, 150 46 S 178 22, 186 18" }),
    svg("circle", { class: "ring", cx: 14, cy: 92, r: 6 }),
    svg("circle", { class: "stop", cx: 86, cy: 60, r: 3 }),
    svg("circle", { class: "stop", cx: 150, cy: 46, r: 3 }),
    svg("path", { class: "mark", d: "M180 8 l6 10 l6 -10 M186 18 v14" }),
  );
}

/** noData({dataDir, status, pulling, onSetDir(path), onChange(), onPull()}) */
export function noData({ dataDir, status, pulling, onSetDir, onChange, onPull }) {
  const input = el("input", {
    attrs: { value: dataDir, "aria-label": "Data folder", spellcheck: "false", "data-focus": "data-dir" },
    on: { change: (e) => e.target.value.trim() && onSetDir(e.target.value.trim()) },
  });
  const why = status.error
    ? el("p", { class: "mono note fall", text: status.errorDetail })
    : !status.canPull
      ? el("p", { class: "note", text: status.pullHint })
      : null;
  return centred(
    "no-data",
    trail(),
    el("h2", { class: "state-title", text: status.error ? status.text : "No prices yet" }),
    el("p", {
      class: "state-text",
      text: "Coppertrail keeps a local copy of the AHledger price archive. Pull once to start — the first pull reads the full history and takes about a minute.",
    }),
    el("div", { class: "folder-row" }, el("label", { class: "input" }, icon("folder", 15), input), el("button", { class: "ctl", text: "Change…", on: { click: onChange } })),
    el(
      "button",
      { class: "btn primary", attrs: { disabled: pulling || !status.canPull }, on: { click: onPull } },
      icon("download", 15),
      pulling ? "Pulling…" : "Pull latest data",
    ),
    why,
    el("p", { class: "note", text: "Patterns become meaningful after about two weeks of history." }),
  );
}

// B: data stale ------------------------------------------------------------------------

/** staleBanner({banner: {title, detail}, status, pulling, onPull(), onDismiss()}) */
export function staleBanner({ banner, status, pulling, onPull, onDismiss }) {
  return el(
    "div",
    { class: "banner", attrs: { role: "status" } },
    el("span", { class: "banner-icon" }, icon("clock", 16)),
    el("span", { class: "banner-text" }, el("b", { text: banner.title }), " ", el("span", { class: "muted", text: banner.detail })),
    el(
      "button",
      { class: "btn primary slim", attrs: { disabled: pulling || !status.canPull, title: status.canPull ? false : status.pullHint }, on: { click: onPull } },
      pulling ? "Pulling…" : "Pull latest data",
    ),
    el("button", { class: "btn ghost square", attrs: { "aria-label": "Dismiss", title: "Dismiss" }, on: { click: onDismiss } }, icon("x", 13)),
  );
}

// C: filter matches nothing ------------------------------------------------------------

/** noMatch({sub, chips: [{label, clear}], hint}, {onClear(partial), onReset()}) */
export function noMatch(nm, { onClear, onReset }) {
  const chips = nm.chips.map((c) =>
    el(
      "span",
      { class: "chip filter-chip" },
      c.label,
      el("button", { attrs: { "aria-label": `Remove filter ${c.label}`, title: "Remove this filter" }, on: { click: () => onClear(c.clear) } }, icon("x", 12)),
    ),
  );
  const hint = nm.hint
    ? el("p", { class: "note" }, `${nm.hint.prefix} `, el("b", { text: nm.hint.label }), ` ${nm.hint.result}`)
    : null;
  return centred(
    "no-match",
    el("span", { class: "state-icon" }, icon("filter", 34)),
    el("h2", { class: "state-title", text: "No items match these filters" }),
    el("p", { class: "state-text", text: nm.sub }),
    el("div", { class: "chips" }, chips),
    hint,
    el("button", { class: "btn ghost", on: { click: onReset } }, icon("reset", 14), "Reset all filters"),
  );
}

// D: too little history ----------------------------------------------------------------

/** The ghost chart: what is there so far, a "today" line, a dotted guess after it. */
function ghostChart() {
  const box = el("div", { class: "ghost-chart", attrs: { "aria-hidden": "true" } });
  box.append(
    svg(
      "svg",
      { viewBox: "0 0 400 150", preserveAspectRatio: "none" },
      svg("path", { class: "so-far", d: "M0 110 L40 96 L80 104 L120 80 L160 88", "vector-effect": "non-scaling-stroke" }),
      svg("path", { class: "to-come", d: "M160 88 L200 70 L240 82 L280 60 L320 72 L360 52 L400 60", "vector-effect": "non-scaling-stroke" }),
    ),
    el("span", { class: "today" }),
    el("span", { class: "today-label", text: "today" }),
  );
  return box;
}

/** needsHistory({title, why, progress, ready, pct}) — from bridge.history_gap(). */
export function needsHistory(g) {
  const bar = el("div", { class: "progress" }, el("div"));
  bar.firstChild.style.width = `${Math.max(0, Math.min(100, g.pct))}%`;
  return el(
    "div",
    { class: "state needs-history", attrs: { role: "status" } },
    el("span", { class: "state-icon accent" }, icon("hourglass", 30)),
    el("h2", { class: "state-title", text: g.title }),
    el("p", { class: "state-text", text: g.why }),
    el("div", { class: "history-progress" }, el("div", { class: "row-between" }, el("span", { text: g.progress }), el("span", { text: g.ready })), bar),
    ghostChart(),
  );
}

// E: loading ------------------------------------------------------------------------------

const bone = (cls) => el("span", { class: "bone " + cls });

/** loading({text, pct?}) — skeleton blocks in --raised keep the layout still. No pct: indeterminate. */
export function loading({ text, pct = null }) {
  const bar = el("div", { class: "loadbar" + (pct == null ? " indeterminate" : "") }, el("div"));
  if (pct != null) bar.firstChild.style.width = `${pct}%`;
  const tile = () => el("div", { class: "card skel-tile" }, bone("w60 h10"), bone("w80 h22"), bone("w50 h9"));
  const bars = el(
    "div",
    { class: "skel-bars" },
    [30, 42, 38, 55, 48, 60, 52, 66, 58, 72, 64, 70, 61, 78].map((h) => {
      const b = bone("skel-bar");
      b.style.height = h + "%";
      return b;
    }),
  );
  return el(
    "div",
    { class: "state loading", attrs: { role: "status", "aria-busy": "true" } },
    el("div", { class: "load-head" }, el("span", { class: "spin" }, icon("refresh", 16)), el("span", { text }), el("span", { class: "spacer" }), pct == null ? null : el("span", { class: "pct", text: `${pct} %` })),
    bar,
    el("div", { class: "skel-tiles" }, tile(), tile(), tile()),
    el("div", { class: "card skel-chart" }, bone("w40 h12"), bone("w25 h9"), bars),
  );
}

// F: pull failed --------------------------------------------------------------------------

/** pullFailed({title, cause, reassurance, request, log}, {showLog, canPull, onRetry(), onToggleLog()}) */
export function pullFailed(f, { showLog, canPull, onRetry, onToggleLog }) {
  return centred(
    "pull-failed",
    el("span", { class: "state-icon fall" }, icon("info", 32)),
    el("h2", { class: "state-title", text: f.title }),
    el("p", { class: "state-text" }, f.cause, " ", f.reassurance),
    el(
      "div",
      { class: "row" },
      el("button", { class: "btn primary", attrs: { disabled: !canPull }, on: { click: onRetry } }, icon("refresh", 15), "Try again"),
      el("button", { class: "btn", attrs: { "aria-expanded": showLog ? "true" : "false" }, on: { click: onToggleLog } }, showLog ? "Hide log" : "Show log"),
    ),
    el("p", { class: "mono note", text: f.request }),
    showLog ? el("pre", { class: "mono log", text: f.log }) : null,
  );
}
