// Style sample (HANDOVER 9, step 6.1): fonts, tabular digits, colours, coins, controls, a chart.
// All numbers are invented sample values, not market data.
import { axisCoins, change, coin } from "./coins.js";
import { barChart, chart, chartCard, legend, lineChart, markerLegend, rangeBar, sparkline } from "./charts.js";
import { el } from "./dom.js";
import { icon } from "./icons.js";
import * as states from "./states.js";

const root = document.getElementById("sample");
const card = (title, sub, ...body) =>
  el("section", { class: "card" }, el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: title }), sub && el("div", { class: "sub", text: sub }))), ...body);

const c = (parts) => ({ parts, text: parts.map(([n, u]) => n.toLocaleString("en-US") + u).join(" ") });

// Header: shield, wordmark, h1
const shield = el("img", { attrs: { src: "icons/app.svg", width: 30, height: 30, alt: "" } });
const wordmark = el("span", { class: "wordmark" }, el("span", { class: "copper", text: "Copper" }), el("span", { class: "trail", text: "trail" }));
wordmark.style.fontSize = "28px";
root.append(
  el("header", { class: "wide head" }, shield, wordmark),
  el("div", { class: "wide" }, el("h1", { class: "h1", text: "Style sample" }), el("div", { class: "sub", text: "17 Oct – 16 Nov 2026 · invented values" })),
);

// Type scale
const types = [
  ["h1", "h1 · Market overview"],
  ["title", "title · Price index"],
  ["display", "display · Coppertrail"],
  ["h2", "h2 · Edit item groups"],
  ["kpi", "kpi · 9,063 / 1,111"],
  ["body", "body · Lowest buyout 0123456789"],
  ["th", "th · Sales per day"],
  ["sub", "sub · 17 Oct – 16 Nov 2026 · 30 d"],
  ["small", "small · Data as of 16 Nov 2026, 08:42"],
];
root.append(
  card(
    "Type scale",
    "Display face for h1 and card titles only",
    el(
      "div",
      { class: "stack" },
      types.map(([role, text]) => {
        const line = el("div", { text });
        for (const p of ["family", "weight", "size", "transform"]) line.style.setProperty(p === "transform" ? "text-transform" : `font-${p}`, `var(--type-${role}-${p})`);
        line.style.letterSpacing = `var(--type-${role}-spacing)`;
        return line;
      }),
    ),
  ),
);

// Colours
const tokens = ["bg0", "bg1", "surface", "raised", "overlay", "text1", "text2", "text3", "textDis", "border", "borderStrong", "grid", "scroll", "accent", "accentHover", "accentPressed", "accentMuted", "accentOn", "s1", "s2", "s3", "s4", "s5", "s6", "rise", "fall", "attention", "attentionBg", "gold", "silver", "copper"];
root.append(
  card(
    "Colours",
    "Dark theme tokens",
    el(
      "div",
      { class: "swatches" },
      tokens.map((t) => {
        const b = el("b");
        b.style.background = `var(--${t})`;
        return el("div", { class: "swatch" }, b, t);
      }),
    ),
  ),
);

// Table with coins and changes
const rows = [
  ["Rugged Leather", "Trade Goods", c([[14, "s"], [95, "c"]]), "▲ +14.2 %", "rise", "9,221"],
  ["Cured Rugged Hide", "Trade Goods", c([[23, "g"], [30, "s"], [98, "c"]]), "▼ −87 %", "fall", "40"],
  ["Black Lotus", "Trade Goods", c([[250, "g"]]), "▲ +3.1 %", "rise", "12"],
  ["Thorium Bar", "Trade Goods", c([[60, "s"]]), "± 0.0 %", "flat", "3,000"],
  ["Light Leather", "Trade Goods", c([[35, "c"]]), "▼ −1.1 %", "fall", "25,000"],
  ["Superior Healing Potion", "Consumable", null, "▲ +488 %", "rise", "1.61 M"],
];
const table = el(
  "table",
  { class: "data" },
  el("thead", {}, el("tr", {}, el("th", { text: "Item" }), el("th", { text: "Class" }), el("th", { class: "num", text: "Lowest buyout" }), el("th", { class: "num", text: "7 d" }), el("th", { class: "num", text: "Sales/day" }))),
  el(
    "tbody",
    {},
    rows.map(([name, cls, price, pct, dir, sales], i) =>
      el("tr", { class: i === 1 ? "selected" : "" }, el("td", { text: name }), el("td", { class: "muted", text: cls }), el("td", { class: "num" }, coin(price)), el("td", { class: "num" }, change(pct, dir)), el("td", { class: "num", text: sales })),
    ),
  ),
);
root.append(card("Table", "Coins, signed changes, tabular digits", table));

// Controls
const seg = el("div", { class: "seg" }, ["24 h", "7 d", "30 d", "All"].map((t) => el("button", { text: t, attrs: { "aria-pressed": t === "30 d" ? "true" : "false" } })));
root.append(
  card(
    "Controls",
    "Default, changed filter, primary, ghost",
    el(
      "div",
      { class: "stack" },
      el("div", { class: "row" }, el("button", { class: "ctl" }, el("span", { class: "label", text: "Groups" }), el("span", { class: "value", text: "All groups" }), icon("chevron", 14)), el("button", { class: "ctl active" }, el("span", { class: "label", text: "Groups" }), el("span", { class: "value", text: "Leather chain, Herbs" }), icon("chevron", 14)), el("label", { class: "input" }, icon("search", 16), el("input", { attrs: { placeholder: "Search items" } }))),
      el("div", { class: "row" }, seg, el("button", { class: "ctl" }, icon("calendar", 16), el("span", { class: "value", text: "17 Oct – 16 Nov 2026" }))),
      el("div", { class: "row" }, el("button", { class: "btn primary", text: "Save groups" }), el("button", { class: "btn", text: "Duplicate" }), el("button", { class: "btn ghost" }, icon("reset", 14), "Reset"), el("button", { class: "btn link" }, icon("download", 14), "Pull latest data"), el("button", { class: "btn", text: "Disabled", attrs: { disabled: true } })),
      el("div", { class: "row" }, el("span", { class: "chip", text: "0" }), el("button", { class: "chip", attrs: { "aria-pressed": "true" }, text: "50" }), el("span", { class: "chip", text: "1,000" }), el("span", { class: "dot rise" }), el("span", { class: "small muted", text: "Data as of 16 Nov 2026, 08:42" }), el("span", { class: "dot attention" }), el("span", { class: "small attention", text: "Data is 3 days old" })),
    ),
  ),
);

// Chart: two invented index series around 100 over 30 days
const start = Date.UTC(2026, 9, 17) / 1000;
const x = Array.from({ length: 30 * 24 }, (_, i) => start + i * 3600);
const scarce = x.map((_, i) => 100 + i * 0.03 + 6 * Math.sin(i / 37) + 2 * Math.sin(i / 5));
const farmable = x.map((_, i) => 100 - i * 0.008 + 3 * Math.sin(i / 51 + 1) + 1.5 * Math.sin(i / 4));
const series = [
  { label: "Scarce goods", color: "s1", width: "primary", fill: true, values: scarce },
  { label: "Farmable goods", color: "s2", width: "secondary", values: farmable },
];
const plot = el("div", { class: "chart" });
const head = el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: "Price index, farmable vs scarce goods" }), el("div", { class: "sub", text: "17 Oct – 16 Nov 2026 · 30 d · 100 = 17 Oct" })), el("div", { class: "row" }, legend(series), el("button", { class: "btn icon", attrs: { title: "Reset zoom" }, on: { click: () => indexChart.reset() } }, icon("reset", 16))));
root.append(el("section", { class: "card wide" }, head, plot));
const indexChart = lineChart(plot, { x, series, refLine: 100, height: 300, format: (v) => v.toFixed(1) });

// Chart building blocks (HANDOVER 8b "Charts in uPlot", Item detail and Movers mock-ups) -------

const section = (title, sub) => el("div", { class: "wide section" }, el("h1", { class: "h1", text: title }), el("div", { class: "sub", text: sub }));
root.append(section("Chart blocks", "Linked x-axes, band, vendor floor, event markers, bars, stale tail, sparkline, range bar"));

// Price and supply: lowest buyout + lower quartile with the band, vendor floor, markers;
// listed quantity as bars below on a linked x-axis, shock bars in s3.
const points = 30 * 4; // 6-hour points
const px = Array.from({ length: points }, (_, i) => start + i * 6 * 3600);
const buyout = px.map((_, i) => 1500 + 220 * Math.sin(i / 9) + (i > 70 && i < 78 ? -520 : 0) + i * 2);
const p25 = buyout.map((v, i) => v + 180 + 60 * Math.sin(i / 5));
const qty = px.map((_, i) => Math.round(9000 + 2500 * Math.sin(i / 7) + (i >= 70 && i < 76 ? 14000 : 0)));
const shock = qty.map((_, i) => i >= 70 && i < 76);
const markers = [
  { t: px[22], kind: "buyout", label: "Buyout · 1,240 units cleared" },
  { t: px[71], kind: "shock", label: "Supply shock · listed qty ×2.4 in 6 h" },
  { t: px[74], kind: "mispricing", label: "Mispricing · 9s 80c vs 15s usual" },
];
const priceSeries = [
  { label: "Lowest buyout", color: "s1", width: "primary", values: buyout },
  { label: "Lower quartile", color: "s2", width: "tertiary", values: p25 },
];
const kilo = (v) => (v >= 1000 ? Math.round(v / 1000) + "k" : String(Math.round(v)));
const priceCard = chartCard({
  title: "Price and supply",
  sub: "17 Oct – 16 Nov 2026 · 30 d · drag to zoom, both plots follow",
  legend: [...priceSeries, { label: "Vendor floor", color: "text3", dashed: true }, { label: "Listed quantity", color: "s6", bars: true }, ...markerLegend()],
  plots: 2,
  className: "wide",
  build: (top, bottom) => [
    chart(top, { x: px, series: priceSeries, bands: [{ upper: 1, lower: 0, color: "s2" }], refLines: [{ value: 750, label: "Vendor floor 7s 50c" }], markers, sync: "sample-item", height: 240, xAxis: false, format: axisCoins }),
    barChart(bottom, { x: px, values: qty, label: "Listed quantity", highlight: shock, highlightLabel: "Listed (supply shock)", sync: "sample-item", height: 140, format: kilo }),
  ],
});
root.append(priceCard.node);
priceCard.mount();

// Stale data: the x-axis runs on to "now", the part after the last point is shaded.
const staleX = x.filter((_, i) => i < 27 * 24);
const staleOpts = () => ({
  x: staleX,
  series: series.map((s) => ({ ...s, fill: false, values: s.values.slice(0, staleX.length) })),
  stale: { from: staleX[staleX.length - 1], to: x[x.length - 1], label: "no data since 13 Nov 07:55" },
  format: (v) => v.toFixed(0),
});
const staleCard = chartCard({
  title: "Data is stale",
  sub: "17 Oct – 16 Nov 2026 · last point 13 Nov 07:55",
  legend: series,
  build: (p) => chart(p, { ...staleOpts(), height: 240 }),
});
const dx = Array.from({ length: 30 }, (_, i) => start + i * 86400);
const margin = dx.map((_, i) => Math.round(400 + 900 * Math.sin(i / 3) + i * 20));
const barCard = chartCard({
  title: "Daily margin",
  sub: "17 Oct – 16 Nov 2026 · bars with a 28 % gap",
  legend: [{ label: "Margin", color: "s6", bars: true }, { label: "Worth it", color: "rise", bars: true }],
  build: (p) =>
    barChart(p, { x: dx, values: margin.map((v) => Math.max(0, v)), label: "Margin", highlight: margin.map((v) => v > 900), highlightColor: "rise", highlightLabel: "Worth it", refLines: [{ value: 900, label: "threshold 9s" }], height: 240, format: axisCoins }),
});
root.append(staleCard.node, barCard.node);
staleCard.mount();
barCard.mount();

// Sparklines and range bars in a table.
const walk = (seed, drift) => Array.from({ length: 28 }, (_, i) => 100 + drift * i + 6 * Math.sin(i / 2 + seed));
const moverRows = [
  ["Waylaid Crate: Journeyman Parts", walk(1, 3), "rise", "▲ +488 %", { low: 3000, high: 6000, usual: 4500, current: 1800 }],
  ["Mote of Unstable Magic", walk(2, -3), "fall", "▼ −98 %", { low: 900, high: 1500, usual: 1200, current: 1100 }],
  ["Thorium Bar", walk(3, 0.1), "rise", "▲ +3.1 %", { low: 5000, high: 7000, usual: 6000, current: 3900 }],
];
const moverTable = el(
  "table",
  { class: "data" },
  el("thead", {}, el("tr", {}, el("th", { text: "Item" }), el("th", { text: "7 d" }), el("th", { class: "num", text: "Price change" }), el("th", { text: "Where it sits" }))),
  el(
    "tbody",
    {},
    moverRows.map(([name, vals, dir, pct, range]) => el("tr", {}, el("td", { text: name }), el("td", {}, sparkline(vals, dir)), el("td", { class: "num" }, change(pct, dir)), el("td", {}, rangeBar(range)))),
  ),
);
root.append(card("Sparkline and range bar", "96 × 26 with end dot · range: typical, usual tick, current", moverTable));

// Layout hooks (HANDOVER 8b "Resizing") ---------------------------------------------------------
const tile = (label, value, foot, extra = false) => el("div", { class: "card" + (extra ? " tile-extra" : "") }, el("div", { class: "label", text: label }), el("div", { class: "kpi", text: value }), el("div", { class: "sub", text: foot }));
root.append(
  section("Layout hooks", "4 tiles, 6 from 2400 px · the 2:1 split stacks at 1440 px"),
  el(
    "div",
    { class: "wide tiles" },
    tile("Items tracked", "1,284", "412 pass filters"),
    tile("Median price · 7 d", "−3.2 %", "invented"),
    tile("Supply · 7 d", "+11.4 %", "invented"),
    tile("Index divergence", "+19.8 pts", "invented"),
    tile("Gold listed", "2,412,000", "ultrawide only", true),
    tile("Mispricings now", "7", "ultrawide only", true),
  ),
  el("div", { class: "wide split" }, card("Two thirds", "split · main"), card("One third", "split · side")),
);

// States (HANDOVER 8b "States", mock-up States.png) ---------------------------------------------
root.append(section("States", "Every value invented · buttons do nothing here"));
const noop = () => {};
const demo = (label, ...body) => el("section", { class: "card state-demo" }, el("div", { class: "demo-label", text: label }), ...body);
const staleMini = el("div", { class: "chart" });
staleMini.style.marginTop = "14px";
root.append(
  el(
    "div",
    { class: "wide states" },
    demo("A · No data yet", states.noData({ dataDir: "D:\\Coppertrail\\data", status: { canPull: true, error: false, text: "No data yet" }, pulling: false, onSetDir: noop, onChange: noop, onPull: noop })),
    demo("B · Data is stale", states.staleBanner({ banner: { title: "Data is 3 days old.", detail: "Charts end on 13 Nov, 07:55." }, status: { canPull: true }, pulling: false, onPull: noop, onDismiss: noop }), staleMini),
    demo(
      "C · Filter matches nothing",
      states.noMatch(
        {
          sub: "0 of 1,284 items · remove one to widen the search",
          chips: [{ label: "Group: Scarce goods" }, { label: "Class: Recipe" }, { label: "Search: “crate”" }, { label: "Min sales/day ≥ 5,000" }],
          hint: { prefix: "Closest: without", label: "Min sales/day ≥ 5,000", result: "→ 38 items" },
        },
        { onClear: noop, onReset: noop },
      ),
    ),
    demo(
      "D · Too little history",
      el("div", { class: "tabs" }, ["Daily rhythm", "Weekend effect", "Reset day"].map((t, i) => el("button", { class: "tab", text: t, attrs: { "aria-selected": i === 2 ? "true" : "false" } }))),
      states.needsHistory({
        title: "Needs 3 more weeks of data",
        why: "“Reset day” needs 6 resets of history. The archive covers 3 so far — too few to separate a pattern from noise.",
        progress: "3 of 6 resets",
        ready: "ready around 7 Dec 2026",
        pct: 50,
      }),
    ),
    demo("E · Loading", states.loading({ text: "Reading 142 days · 1,284 items…", pct: 62 })),
    demo(
      "F · Pull failed",
      states.pullFailed(
        {
          title: "Pull failed",
          cause: "git stopped: unable to access the data repository: Could not resolve host.",
          reassurance: "Your local archive is unchanged — everything up to 16 Nov, 08:42 is still here.",
          request: "git pull --ff-only · exit 1 · 08:44:10",
          log: "fatal: unable to access the data repository: Could not resolve host",
        },
        { showLog: false, canPull: true, onRetry: noop, onToggleLog: noop },
      ),
    ),
  ),
);
chart(staleMini, { ...staleOpts(), height: 230 });
