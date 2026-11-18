// Item detail (HANDOVER 8b "Views", mock-up ItemDetail): the item list panel on the left,
// the selected item on the right. Data: bridge.item_list(sort) and bridge.item_detail(id).
// The list and the detail load separately, so picking another item keeps the list (and its
// scroll position and search) in place.
import { call } from "./api.js";
import { axisCoins, axisCount, change, coin } from "./coins.js";
import { barChart, chart, chartCard, MARKERS, markerLegend } from "./charts.js";
import { el, replace } from "./dom.js";
import { itemIcon, withIcon } from "./itemicon.js";
import { icon } from "./icons.js";
import { closePopover, openPopover } from "./popover.js";
import * as states from "./states.js";
import { noteCard, placeBanner, staleTail, tile, viewHead } from "./viewkit.js";

const view = {
  root: null,
  listBox: null,
  main: null,
  listKey: null,
  detailKey: null,
  listSeq: 0,
  detailSeq: 0,
  sort: "sales",
  search: "",
  rows: [],
  truncated: false,
  pinned: null, // item last asked to be pinned to the list
  selected: null,
};


/** render(container, state, banner, nav) */
export function render(container, state, banner, nav) {
  const base = JSON.stringify([state.dataDir, state.generation, state.status.lastPoint, state.filters, state.groups, state.window]);
  if (!(view.root && view.root.parentNode === container)) {
    skeleton(container, banner, state);
    view.listKey = view.detailKey = null;
  } else placeBanner(container, banner, view.root);
  const listKey = base + "|" + view.sort;
  if (view.listKey !== listKey) {
    view.listKey = listKey;
    loadList(state, nav, base);
  } else showDetail(state, nav, base);
}

// Layout ----------------------------------------------------------------------------------

function skeleton(container, banner, state) {
  const search = el("input", {
    attrs: { placeholder: "Search this list", "aria-label": "Search this list", value: view.search, spellcheck: "false" },
    on: {
      input: (e) => {
        view.search = e.target.value;
        applySearch();
      },
    },
  });
  view.listBox = el("div", { class: "item-rows", attrs: { role: "listbox", "aria-label": "Items" } });
  const panel = el(
    "aside",
    { class: "card item-list" },
    el("label", { class: "input" }, icon("search", 15), search),
    el("div", { class: "item-list-head" }, el("span", { class: "sub list-sub", text: "" }), el("button", { class: "btn ghost sort-btn" }, "Sort", icon("chevron", 13))),
    view.listBox,
  );
  view.main = el("div", { class: "item-main" }, viewHead("Item detail", state.items.sub), states.loading({ text: "Reading prices…" }));
  view.root = el("div", { class: "view-body itemview" }, panel, view.main);
  replace(container, banner, view.root);
  container.scrollTop = 0;
}

// List ------------------------------------------------------------------------------------

async function loadList(state, nav, base) {
  const seq = ++view.listSeq;
  view.root.querySelector(".item-list").classList.add("refreshing");
  try {
    const list = await call("item_list", view.sort, nav.item ?? null); // keeps the shown item listed
    if (seq !== view.listSeq || !view.root.isConnected) return;
    view.rows = list.rows;
    view.truncated = !!list.more;
    fillList(list, nav, state);
    showDetail(state, nav, base);
  } catch (err) {
    if (seq === view.listSeq) replace(view.listBox, el("p", { class: "card-note fall", text: `Could not load the list: ${err}` }));
    view.listKey = null;
  } finally {
    if (seq === view.listSeq) view.root.querySelector(".item-list")?.classList.remove("refreshing");
  }
}

function fillList(list, nav, state) {
  const panel = view.root.querySelector(".item-list");
  panel.querySelector(".list-sub").textContent = list.sub;
  const sortBtn = panel.querySelector(".sort-btn");
  sortBtn.onclick = () => sortMenu(sortBtn, list.sorts, state, nav);
  replace(
    view.listBox,
    list.rows.map((r) =>
      el(
        "button",
        { class: "item-row", attrs: { role: "option", "data-id": r.id, "data-name": r.name.toLowerCase(), "aria-selected": "false" }, on: { click: () => nav.selectItem(r.id) } },
        el("span", { class: "item-name" }, withIcon(r.id, r.name)),
        el("span", { class: "item-price" }, coin(r.price)),
        el("span", { class: "item-class sub", text: r.class }),
        el("span", { class: "item-change" }, r.change ? change(r.change.text, r.change.dir) : el("span", { class: "muted", text: "–" })),
      ),
    ),
    list.more ? el("p", { class: "card-note list-more", text: `${list.more} · narrow the filters or search to find others` }) : null,
  );
  applySearch();
}

function applySearch() {
  const needle = view.search.trim().toLowerCase();
  for (const row of view.listBox.querySelectorAll(".item-row")) row.hidden = needle !== "" && !row.dataset.name.includes(needle);
}

function sortMenu(anchor, sorts, state, nav) {
  const menu = el(
    "div",
    {},
    sorts.map((s) =>
      el(
        "button",
        {
          attrs: { role: "menuitemradio", "aria-checked": s.key === view.sort ? "true" : "false" },
          on: {
            click: () => {
              closePopover();
              if (s.key === view.sort) return;
              view.sort = s.key;
              const base = view.listKey.slice(0, view.listKey.lastIndexOf("|"));
              view.listKey = base + "|" + view.sort;
              loadList(state, nav, base);
            },
          },
        },
        `Sort by ${s.label}`,
      ),
    ),
  );
  openPopover(anchor, menu, { className: "menu" });
}

function markSelected() {
  for (const row of view.listBox.querySelectorAll(".item-row")) {
    const on = Number(row.dataset.id) === view.selected;
    row.classList.toggle("selected", on);
    row.setAttribute("aria-selected", on ? "true" : "false");
  }
}

// Detail ----------------------------------------------------------------------------------

function showDetail(state, nav, base) {
  if (!view.rows.length) {
    view.selected = null;
    replace(view.main, viewHead("Item detail", state.items.sub), el("p", { class: "card-note", text: "No items in this filter." }));
    return;
  }
  // The item from the frame (a click here, a link from another view) when this list has it.
  // A long list shows only its first rows: ask once more with that item pinned to it.
  const wanted = nav.item;
  const listed = view.rows.some((r) => r.id === wanted);
  if (wanted != null && !listed && view.truncated && view.pinned !== wanted) {
    view.pinned = wanted;
    loadList(state, nav, base);
    return;
  }
  view.selected = listed ? wanted : view.rows[0].id;
  markSelected();
  const key = base + "|" + view.selected;
  if (view.detailKey === key) return;
  view.detailKey = key;
  loadDetail(state, nav, view.selected);
}

async function loadDetail(state, nav, id) {
  const seq = ++view.detailSeq;
  view.main.classList.add("refreshing");
  try {
    const d = await call("item_detail", id);
    if (seq !== view.detailSeq || !view.root.isConnected) return;
    buildDetail(d, state, nav);
    view.root.querySelector(".item-row.selected")?.scrollIntoView({ block: "nearest" });
  } catch (err) {
    if (seq === view.detailSeq) replace(view.main, viewHead("Item detail", ""), el("p", { class: "card-note fall", text: `Could not load this item: ${err}` }));
    view.detailKey = null;
  } finally {
    if (seq === view.detailSeq) view.main.classList.remove("refreshing");
  }
}

function buildDetail(d, state, nav) {
  if (d.missing) {
    replace(view.main, viewHead("Item detail", ""), el("p", { class: "card-note", text: d.note }));
    return;
  }
  const id = d.head.id;
  const addBtn = el("button", { class: "btn ghost" }, icon("star", 14), "Add to group");
  addBtn.addEventListener("click", () => groupMenu(addBtn, d.groups, id, nav));
  const tools = el(
    "div",
    { class: "row" },
    addBtn,
    el("button", { class: "btn ghost", on: { click: () => nav.go("patterns", { item: id }) } }, icon("patterns", 14), "Show in patterns"),
  );
  const stale = staleTail(state);
  const cards = [];
  const price = priceCard(d.chart, stale, cards);
  const bottom = el("div", { class: "split-even" }, profileCard(d.profile, cards), eventsCard(d.events));
  replace(view.main, viewHead(d.head.name, d.head.sub, tools, itemIcon(d.head.id, true)), el("div", { class: "tiles five" }, d.tiles.map(tile)), price, bottom);
  for (const c of cards) c.mount();
}

function groupMenu(anchor, groups, id, nav) {
  const items = groups.length
    ? groups.map((g) =>
        el(
          "button",
          {
            attrs: { disabled: g.member, "aria-checked": g.member ? "true" : "false", role: "menuitemcheckbox", title: g.member ? "Already in this group" : false },
            on: {
              click: async () => {
                closePopover();
                nav.setState(await call("add_to_group", g.name, id));
              },
            },
          },
          g.member ? icon("check", 14) : el("span", { class: "menu-gap" }),
          g.name,
        ),
      )
    : [el("p", { class: "card-note", text: "No groups yet." })];
  openPopover(anchor, el("div", {}, items), { className: "menu" });
}

function priceCard(c, stale, cards) {
  if (!c?.x) return noteCard("Price and supply", c);
  const priceSeries = [
    { label: "Lowest buyout", color: "s1", width: "primary", values: c.min, format: axisCoins },
    { label: "Lower quartile", color: "s2", width: "tertiary", values: c.p25, format: axisCoins },
  ];
  const legendItems = [
    ...priceSeries,
    { label: "Spread", color: "s2", bars: true },
    c.vendor ? { label: "Vendor floor", color: "text3", dashed: true } : null,
    { label: "Listed quantity", color: "s6", bars: true },
  ].filter(Boolean);
  const card = chartCard({
    title: "Price and supply",
    sub: c.sub,
    legend: legendItems,
    legend2: markerLegend(),
    plots: 2,
    zoom: true,
    className: "price-card",
    build: (top, bottom) => [
      chart(top, {
        x: c.x,
        series: priceSeries,
        bands: [{ upper: 1, lower: 0, color: "s2" }],
        refLines: c.vendor ? [{ value: c.vendor.value, label: c.vendor.label }] : [],
        markers: c.markers,
        sync: "item-detail",
        height: 280,
        xAxis: false,
        format: axisCoins,
        yWhole: true,
        stale,
      }),
      barChart(bottom, {
        x: c.x,
        values: c.quantity,
        label: "Listed quantity",
        highlight: c.shock.some(Boolean) ? c.shock : null,
        highlightLabel: "Listed (supply shock)",
        sync: "item-detail",
        height: 130,
        format: axisCount,
        stale,
      }),
    ],
  });
  cards.push(card);
  return card.node;
}

function profileCard(p, cards) {
  if (!p?.hours) return noteCard("Hour-of-day profile", p);
  const only = (h) => p.values.map((v, i) => (i === h ? v : null));
  const base = p.values.map((v, i) => (i === p.cheapest.hour || i === p.dearest.hour ? null : v));
  const fmt1 = (v) => Math.round(v).toString();
  const series = [
    { label: "Index", color: "s6", bars: true, values: base },
    { label: "Cheapest hour", color: "rise", bars: true, values: only(p.cheapest.hour) },
    { label: "Dearest hour", color: "fall", bars: true, values: only(p.dearest.hour) },
  ];
  const card = chartCard({
    title: "Hour-of-day profile",
    sub: p.sub,
    tools: p.spread ? el("span", { class: "chip", text: p.spread }) : null,
    reset: false,
    build: (plot) =>
      chart(plot, {
        x: p.hours,
        xHours: true,
        series,
        yFromZero: false,
        refLines: [{ value: 100 }],
        labels: [
          { x: p.dearest.hour, y: p.values[p.dearest.hour], text: p.dearest.text, color: "fall", row: 0 },
          { x: p.cheapest.hour, y: p.values[p.cheapest.hour], text: p.cheapest.text, color: "rise", row: 1 },
        ],
        height: 220,
        format: fmt1,
      }),
  });
  cards.push(card);
  return card.node;
}

function eventsCard(ev) {
  const head = el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: "Events" }), el("div", { class: "sub", text: ev?.sub ?? "" })));
  if (!ev?.rows?.length) return el("section", { class: "card" }, head, el("p", { class: "card-note", text: ev?.note ?? "No events." }));
  const table = el(
    "table",
    { class: "data" },
    el("thead", {}, el("tr", {}, el("th", { text: "When" }), el("th", { text: "Type" }), el("th", { text: "Detail" }))),
    el(
      "tbody",
      {},
      ev.rows.map((r) => {
        const kind = MARKERS[r.kind];
        const mark = el("i", { class: "marker " + kind.shape });
        mark.style.setProperty("--marker", `var(--${kind.color})`);
        return el("tr", {}, el("td", { class: "muted", text: r.when }), el("td", {}, el("span", { class: "event-type" }, mark, r.type)), el("td", { class: "wrap", text: r.detail }));
      }),
    ),
  );
  return el("section", { class: "card events-card" }, head, el("div", { class: "table-scroll" }, table));
}
