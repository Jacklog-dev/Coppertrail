// Patterns (HANDOVER 8b "Views", mock-ups PatternsRhythm and PatternsSpreads, States D).
// Data: bridge.patterns(key, select, item, sort). The payload is generic (tabs, basis line,
// charts, ranked table with typed cells), so this file knows none of the 12 jobs.
import { call } from "./api.js";
import { axisCoins, axisCount, axisPercent, axisSigned, change, coin } from "./coins.js";
import { chart, chartCard, markerLegend } from "./charts.js";
import { el, replace } from "./dom.js";
import { icon } from "./icons.js";
import { closePopover, openPopover } from "./popover.js";
import * as states from "./states.js";
import { noteCard, staleTail, viewHead, viewHost } from "./viewkit.js";

const host = viewHost("patterns");
// What the user picked here; `item` is the last item handed over from Item detail.
const pick = { key: null, select: null, sort: null, item: null, handover: 0 };
const deepLink = location.hash.match(/^#patterns\/(\w+)/); // #patterns/<key> (--tab)
if (deepLink) pick.key = deepLink[1];

const Y = {
  percent: axisPercent,
  coins: axisCoins,
  count: axisCount,
  points: axisSigned,
  index: (v) => Math.round(v).toString(),
  plain: (v) => (Math.abs(v) < 10 ? v.toFixed(2) : Math.round(v).toLocaleString("en-US")),
};

/** render(container, state, banner, nav) */
export function render(container, state, banner, nav) {
  // "Show in patterns" on Item detail: chart that item in the current tab, once per click.
  if (nav?.item != null && nav.handover !== pick.handover) {
    pick.handover = nav.handover;
    pick.item = nav.item;
    pick.select = null;
  }
  const base = [state.dataDir, state.status.lastPoint, state.filters, state.groups, state.window];
  const key = JSON.stringify([...base, pick.key, pick.select, pick.sort, pick.item]);
  const head = viewHead("Patterns", state.items.sub);
  const rerender = () => render(container, state, banner, nav);
  host.show(container, banner, key, head, async (root, isCurrent) => {
    const data = await call("patterns", pick.key, pick.select, pick.item, pick.sort);
    if (!isCurrent()) return;
    build(root, data, state, rerender);
  });
}

function build(root, data, state, rerender) {
  const choose = (patch) => {
    Object.assign(pick, patch);
    rerender();
  };
  const tabs = el(
    "div",
    { class: "tabs", attrs: { role: "tablist", "aria-label": "Patterns" } },
    data.tabs.map((t) =>
      el(
        "button",
        {
          class: "tab",
          attrs: { role: "tab", "aria-selected": t.key === data.key ? "true" : "false", title: `Pattern ${t.number}` },
          on: { click: () => t.key !== data.key && choose({ key: t.key, select: null, sort: null }) },
        },
        t.title,
        t.chip ? el("span", { class: "chip tab-chip", text: t.chip }) : null,
      ),
    ),
  );
  const parts = [viewHead("Patterns", data.sub), tabs];
  if (data.basis) parts.push(basisLine(data.basis));
  const cards = [];
  if (data.state === "ready") parts.push(readyBody(data, state, cards, choose));
  else if (data.state === "history") parts.push(el("section", { class: "card pattern-state" }, states.needsHistory(data.gap)));
  else if (data.state === "waiting") parts.push(el("section", { class: "card pattern-state" }, waiting(data.waiting)));
  else parts.push(el("p", { class: "card-note fall", text: data.error ?? "Could not compute this pattern." }));
  replace(root, ...parts);
  for (const c of cards) c.mount();
  root.querySelector(".ranked tr.selected")?.scrollIntoView({ block: "nearest" });
}

function basisLine(b) {
  return el(
    "div",
    { class: "basis", attrs: { title: b.detail } },
    el("span", { class: "basis-icon" }, icon("info", 14)),
    el("span", { class: "basis-text" }, el("b", { text: b.lead }), b.text),
    el("span", { class: "basis-method", text: b.method }),
  );
}

/** "Waiting for data": the job's input table is still empty (not an error). */
function waiting(w) {
  return el(
    "div",
    { class: "state waiting", attrs: { role: "status" } },
    el("span", { class: "state-icon accent" }, icon("clock", 30)),
    el("h2", { class: "state-title", text: w.title }),
    el("p", { class: "state-text", text: w.text }),
  );
}

function readyBody(data, state, cards, choose) {
  const stale = staleTail(state);
  const charts = (data.charts ?? []).map((c) => patternChart(c, cards, stale));
  if (!charts.length) charts.push(noteCard("Nothing to chart", { note: "Pick a row to chart it." }));
  return el(
    "div",
    { class: "pattern-grid" },
    el("div", { class: "pattern-charts" }, charts),
    el("div", { class: "pattern-side" }, rankedTable(data.table, choose)),
  );
}

/** One chart from the generic payload (see patternview.py). */
function patternChart(c, cards, stale) {
  if (c.note || !c.x) return noteCard(c.title, c);
  const timeX = c.xKind === "time" || c.xKind === "day";
  const kinds = [...new Set((c.markers ?? []).map((m) => m.kind))];
  const card = chartCard({
    title: c.title,
    sub: c.sub,
    legend: c.legend ?? [],
    legend2: kinds.length ? markerLegend(kinds) : null,
    reset: timeX,
    build: (p) =>
      chart(p, {
        x: c.x,
        series: c.series.map((s) => ({ width: "secondary", ...s })),
        height: c.height ?? 300,
        format: Y[c.y] ?? Y.plain,
        bands: c.bands ?? [],
        refLines: c.refLines ?? [],
        vLines: c.vLines ?? [],
        markers: c.markers ?? [],
        labels: c.labels,
        xHours: c.xKind === "hour",
        xLabels: c.xKind === "cat" ? c.xLabels : undefined,
        xSuffix: c.xKind === "num" ? c.xSuffix ?? "" : undefined,
        tipDate: c.xKind === "day" ? "day" : undefined,
        tipExtra: (c.tipExtra ?? []).map((t) => ({ ...t, format: (v) => v })),
        yWhole: c.y === "coins",
        yFromZero: c.yFromZero,
        barPad: timeX && c.series.some((s) => s.bars),
        stale: timeX ? stale : null,
      }),
  });
  cards.push(card);
  return card.node;
}

// Ranked table ---------------------------------------------------------------------------------

function cell(kind, v) {
  if (kind === "rank") return el("td", { class: "muted rank", text: v });
  if (kind === "item") return el("td", { class: "item-cell" }, el("div", { class: "cell-name", text: v.name }), v.sub ? el("div", { class: "sub", text: v.sub }) : null);
  if (kind === "muted") return el("td", { class: "muted", text: v });
  if (kind === "text") return el("td", { text: v });
  if (kind === "num") return el("td", { class: "num", text: v });
  if (kind === "change") return el("td", { class: "num" }, v ? change(v.text, v.dir) : el("span", { class: "muted", text: "–" }));
  if (kind === "coin") return el("td", { class: "num" }, coin(v));
  if (kind === "level") return el("td", { class: "level " + v.tone, text: v.text });
  if (kind === "bar") {
    const fill = el("span", { class: "bar-fill" });
    fill.style.width = `${Math.max(0, Math.min(100, v.share * 100))}%`;
    fill.style.background = `var(--${v.color})`;
    return el("td", { class: "num" }, el("span", { class: "cell-bar" }, el("span", { class: "bar-track" }, fill), el("span", { class: "bar-text", text: v.text })));
  }
  return el("td", { text: String(v ?? "") });
}

function rankedTable(t, choose) {
  const sortLabel = t.sorts.find((s) => s.key === t.sort)?.label ?? t.sort;
  const sortBtn = el("button", { class: "ctl sort-btn" }, el("span", { class: "label muted", text: "Sort:" }), el("span", { class: "value", text: sortLabel }), icon("chevron", 14));
  sortBtn.addEventListener("click", () => sortMenu(sortBtn, t, choose));
  const head = el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: t.title })), sortBtn);
  const table = el(
    "table",
    { class: "data ranked" },
    el("thead", {}, el("tr", {}, t.columns.map((c) => el("th", { class: c.num ? "num" : c.kind === "rank" ? "rank" : "", text: c.label })))),
    el(
      "tbody",
      {},
      t.rows.map((r) =>
        el(
          "tr",
          {
            class: r.id === t.selected ? "selected" : "",
            attrs: { tabindex: "0", "aria-selected": r.id === t.selected ? "true" : "false" },
            on: {
              click: () => r.id !== t.selected && choose({ select: r.id, item: null }),
              keydown: (e) => e.key === "Enter" && r.id !== t.selected && choose({ select: r.id, item: null }),
            },
          },
          t.columns.map((c, i) => cell(c.kind, r.cells[i])),
        ),
      ),
    ),
  );
  return el(
    "section",
    { class: "card ranked-card" },
    head,
    el("div", { class: "ranked-scroll" }, table, t.note ? el("p", { class: "card-note", text: t.note }) : null, t.more ? el("p", { class: "card-note", text: t.more }) : null),
  );
}

function sortMenu(anchor, t, choose) {
  const menu = el(
    "div",
    {},
    t.sorts.map((s) =>
      el(
        "button",
        {
          attrs: { role: "menuitemradio", "aria-checked": s.key === t.sort ? "true" : "false" },
          on: {
            click: () => {
              closePopover();
              if (s.key !== t.sort) choose({ sort: s.key });
            },
          },
        },
        `Sort by ${s.label}`,
      ),
    ),
  );
  openPopover(anchor, menu, { className: "menu" });
}
