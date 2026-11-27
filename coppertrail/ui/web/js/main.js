// The one screen: item list on the left, the picked item's detail on the right.
import { call } from "./api.js";
import { coin, change } from "./coins.js";
import { el, replace } from "./dom.js";
import { loadIcons, withIcon } from "./itemicon.js";
import { priceChart } from "./chart.js";

const $ = (id) => document.getElementById(id);
const state = { rows: [], at: null, kind: "trade", query: "", sort: "name", dir: 1, selected: null, range: "7d" };
let dropChart = null;
let detailToken = 0;

// List ------------------------------------------------------------------------------------

function visibleRows() {
  const q = state.query.trim().toLowerCase();
  const pool = state.kind === "trade" ? state.rows.filter((r) => r.trade) : state.rows;
  const rows = q ? pool.filter((r) => r.name.toLowerCase().includes(q) || String(r.id) === q) : pool.slice();
  const key = state.sort === "price" ? (r) => r.copper : (r) => r.name.toLowerCase();
  rows.sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0) * state.dir);
  return rows;
}

function renderList() {
  const rows = visibleRows();
  replace(
    $("rows"),
    rows.map((r) =>
      el(
        "div",
        {
          class: "row" + (r.id === state.selected ? " selected" : ""),
          attrs: { role: "option", "data-id": r.id, "aria-selected": r.id === state.selected },
          on: { click: () => select(r.id) },
        },
        withIcon(r.id, r.name),
        el("span", { class: "num" }, coin(r.price)),
      ),
    ),
  );
  const total = state.kind === "trade" ? state.rows.filter((r) => r.trade).length : state.rows.length;
  const noun = state.kind === "trade" ? "trade goods" : "items";
  const shown = rows.length === total ? `${total.toLocaleString("en-US")} ${noun} listed` : `${rows.length.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} ${noun}`;
  $("list-foot").textContent = state.at ? `${shown} · prices of ${state.at}` : shown;
  $("sort-name").classList.toggle("active", state.sort === "name");
  $("sort-price").classList.toggle("active", state.sort === "price");
  $("sort-name").textContent = "Item" + (state.sort === "name" ? (state.dir > 0 ? " ▲" : " ▼") : "");
  $("sort-price").textContent = "Lowest price" + (state.sort === "price" ? (state.dir > 0 ? " ▲" : " ▼") : "");
}

function sortBy(key) {
  state.dir = state.sort === key ? -state.dir : 1;
  state.sort = key;
  renderList();
}

async function loadItems() {
  const data = await call("items");
  state.rows = data.rows;
  state.at = data.at;
  renderList();
}

// Detail ----------------------------------------------------------------------------------

function select(id) {
  state.selected = id;
  history.replaceState(null, "", `#item/${id}`);
  for (const row of $("rows").children) {
    const on = Number(row.dataset.id) === id;
    row.classList.toggle("selected", on);
    row.setAttribute("aria-selected", on);
  }
  loadDetail();
}

const RANGE_TEXT = { "24h": "24 h", "7d": "7 days", "30d": "30 days", all: "All" };

async function loadDetail() {
  const token = ++detailToken;
  const d = await call("item", state.selected, state.range);
  if (token !== detailToken) return; // a newer click won
  if (dropChart) dropChart();
  dropChart = null;

  const readout = el("div", { class: "readout" });
  const chartBox = el("div", { class: "chart-wrap" });
  const sub = el(
    "div",
    { class: "d-sub" },
    d.change && el("span", {}, change(d.change.text, d.change.direction)),
    el("span", { text: d.listed ? `Lowest listing at ${d.at}` : d.lastSeen ? `Not listed now · last seen ${d.lastSeen}` : "Not listed" }),
  );
  const ranges = el(
    "div",
    { class: "ranges", attrs: { role: "group", "aria-label": "Range" } },
    d.ranges.map((r) =>
      el("button", {
        class: "btn" + (r === d.range ? " on" : ""),
        text: RANGE_TEXT[r],
        attrs: { type: "button", "aria-pressed": r === d.range },
        on: { click: () => { state.range = r; loadDetail(); } },
      }),
    ),
  );
  const stats = el(
    "div",
    { class: "stats" },
    el("span", {}, el("b", { text: `Lowest in ${RANGE_TEXT[d.range].toLowerCase()}` }), coin(d.low)),
    el("span", {}, el("b", { text: `Highest in ${RANGE_TEXT[d.range].toLowerCase()}` }), coin(d.high)),
  );
  replace(
    $("detail"),
    withIcon(d.id, el("span", { class: "d-name", text: d.name }), true),
    el("div", { class: "d-price" }, coin(d.price)),
    sub,
    ranges,
    chartBox,
    readout,
    stats,
  );
  const idle = "Hover the chart to see a single hour.";
  readout.textContent = idle;
  dropChart = priceChart(chartBox, d.x, d.y, (text) => (readout.textContent = text ?? idle));
}

function emptyDetail() {
  replace($("detail"), el("p", { class: "empty", text: state.rows.length ? "Pick an item to see its lowest price and history." : "No data yet." }));
}

// Sync and status -------------------------------------------------------------------------

let syncing = false;

function showStatus(s) {
  const text = $("sync-text");
  text.classList.toggle("error", !s.syncing && !s.ok);
  if (s.syncing) {
    text.textContent = s.total ? `Syncing from the Pi · ${s.done} of ${s.total} snapshots` : "Syncing from the Pi…";
  } else if (!s.ok && s.message) {
    text.textContent = s.message;
  } else {
    text.textContent = s.last ? `Latest hour ${s.last}` : "No data yet";
  }
  $("sync-btn").disabled = s.syncing;
  const span = s.hours ? `${s.hours.toLocaleString("en-US")} hours · ${s.first} – ${s.last}` : "";
  replace($("strip"), el("span", { text: s.credit }), el("span", { class: "right", text: span }));
}

async function poll() {
  const s = await call("status");
  showStatus(s);
  if (syncing && !s.syncing) {
    // a sync just finished: reload what it changed
    await loadItems();
    if (state.selected != null) loadDetail();
    else emptyDetail();
  }
  syncing = s.syncing;
  setTimeout(poll, s.syncing ? 1000 : 30000);
}

async function syncNow() {
  showStatus(await call("sync_now"));
  syncing = true;
}

// Start -----------------------------------------------------------------------------------

async function start() {
  $("search").addEventListener("input", (e) => {
    state.query = e.target.value;
    renderList();
  });
  for (const btn of $("kind").children) {
    btn.addEventListener("click", () => {
      state.kind = btn.dataset.kind;
      for (const b of $("kind").children) {
        b.classList.toggle("on", b === btn);
        b.setAttribute("aria-pressed", b === btn);
      }
      renderList();
    });
  }
  $("sort-name").addEventListener("click", () => sortBy("name"));
  $("sort-price").addEventListener("click", () => sortBy("price"));
  $("sync-btn").addEventListener("click", syncNow);
  setInterval(syncNow, 30 * 60 * 1000); // new hours arrive once an hour

  await loadIcons();
  await loadItems();
  const m = location.hash.match(/^#item\/(\d+)$/);
  if (m) select(Number(m[1]));
  else emptyDetail();
  poll();
}

start();
