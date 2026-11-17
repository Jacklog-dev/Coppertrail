// Style sample (HANDOVER 9, step 6.1): fonts, tabular digits, colours, coins, controls, a chart.
// All numbers are invented sample values, not market data.
import { change, coin } from "./coins.js";
import { legend, lineChart } from "./charts.js";
import { el } from "./dom.js";
import { icon } from "./icons.js";

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
const head = el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: "Price index, farmable vs scarce goods" }), el("div", { class: "sub", text: "17 Oct – 16 Nov 2026 · 30 d · 100 = 17 Oct" })), el("div", { class: "row" }, legend(series), el("button", { class: "btn icon", attrs: { title: "Reset zoom" }, on: { click: () => chart.reset() } }, icon("reset", 16))));
root.append(el("section", { class: "card wide" }, head, plot));
const chart = lineChart(plot, { x, series, refLine: 100, height: 300, format: (v) => v.toFixed(1) });
