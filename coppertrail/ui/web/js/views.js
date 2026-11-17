// The four views. Until their real content exists (HANDOVER 9, step 6.3) each one lists the
// items that pass the filters, so the filter bar can be checked end to end.
import { coin } from "./coins.js";
import { el, replace } from "./dom.js";
import { VIEWS } from "./navrail.js";

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

/** render(container, state, viewId, banner?) — `banner` (the stale-data notice) goes on top. */
export function render(container, state, viewId, banner = null) {
  const view = VIEWS.find((v) => v.id === viewId) ?? VIEWS[0];
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
    itemTable(items.rows),
  );
  replace(container, banner, head, body);
  container.scrollTop = 0;
}
