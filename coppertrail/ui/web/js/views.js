// The four views. Market overview and Item detail are real (overview.js, itemdetail.js);
// Patterns and Movers still list the items that pass the filters until their session lands.
import { coin } from "./coins.js";
import { el, replace } from "./dom.js";
import * as itemdetail from "./itemdetail.js";
import { VIEWS } from "./navrail.js";
import * as overview from "./overview.js";

function itemTable(rows) {
  return el(
    "table",
    { class: "data" },
    el(
      "thead",
      {},
      el("tr", {}, el("th", { text: "Item" }), el("th", { text: "Class" }), el("th", { class: "num", text: "Lowest buyout" }), el("th", { class: "num", text: "Sales/day" })),
    ),
    el(
      "tbody",
      {},
      rows.map((r) =>
        el("tr", {}, el("td", { text: r.name }), el("td", { class: "muted", text: r.class }), el("td", { class: "num" }, coin(r.price)), el("td", { class: "num", text: r.salesPerDay })),
      ),
    ),
  );
}

function placeholder(container, state, view, banner) {
  const { items, window } = state;
  const head = el(
    "header",
    { class: "view-head" },
    el("div", {}, el("h1", { class: "h1", text: view.label }), el("p", { class: "sub", text: `${items.sub} · ${window.label}` })),
  );
  const more = items.shown > items.rows.length ? `first ${items.rows.length.toLocaleString("en-US")} shown` : "";
  const body = el(
    "section",
    { class: "card" },
    el(
      "div",
      { class: "card-head" },
      el("div", {}, el("h2", { class: "card-title", text: "Items in the filter" }), el("div", { class: "sub", text: more || "Placeholder until this view is built" })),
    ),
    items.rows.length ? itemTable(items.rows) : el("p", { class: "muted", text: "This data folder has prices but no item names yet." }),
  );
  replace(container, banner, head, body);
  container.scrollTop = 0;
}

/**
 * render(container, state, viewId, banner?, nav) — `banner` (the stale-data notice) goes on
 * top; `nav` lets a view switch views or pick an item (main.js).
 */
export function render(container, state, viewId, banner = null, nav = null) {
  const view = VIEWS.find((v) => v.id === viewId) ?? VIEWS[0];
  if (view.id === "overview") return overview.render(container, state, banner, nav);
  if (view.id === "item") return itemdetail.render(container, state, banner, nav);
  return placeholder(container, state, view, banner);
}
