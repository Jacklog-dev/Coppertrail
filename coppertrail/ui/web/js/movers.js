// Movers & outliers (HANDOVER 8b "Views", mock-up Movers). Data: bridge.movers(range) for the
// risers and fallers, bridge.mispricings_now(threshold) for the table; each reloads on its own
// when its control changes.
import { call } from "./api.js";
import { change, coin } from "./coins.js";
import { rangeBar, sparkline } from "./charts.js";
import { el, replace } from "./dom.js";
import { icon } from "./icons.js";
import { closePopover, openPopover } from "./popover.js";
import { viewHead, viewHost } from "./viewkit.js";

const host = viewHost("movers");
const RANGES = [
  { key: "24h", label: "24 h" },
  { key: "7d", label: "7 d" },
  { key: "30d", label: "30 d" },
];
const deepLink = location.hash.match(/^#movers\/(\w+)/); // #movers/<range> (--tab 24h)
const pick = { range: RANGES.some((r) => r.key === deepLink?.[1]) ? deepLink[1] : "7d", threshold: 0.7 };

/** render(container, state, banner, nav) */
export function render(container, state, banner, nav) {
  const key = JSON.stringify([state.dataDir, state.status.lastPoint, state.filters, state.groups]);
  host.show(container, banner, key, head(state.items.sub, null), async (root, isCurrent) => {
    const [moves, mis] = await Promise.all([call("movers", pick.range), call("mispricings_now", pick.threshold)]);
    if (!isCurrent()) return;
    const top = el("div", { class: "movers-top" });
    const bottom = el("div", { class: "movers-bottom" });
    // Only the newest click of each control may draw (answers can come back out of order).
    const seq = { top: 0, bottom: 0 };
    const reload = async (part, node, name, arg, draw) => {
      const n = ++seq[part];
      node.classList.add("refreshing");
      try {
        const m = await call(name, arg);
        if (isCurrent() && n === seq[part]) draw(m);
      } finally {
        if (n === seq[part]) node.classList.remove("refreshing");
      }
    };
    const reloadTop = (range) => {
      pick.range = range;
      return reload("top", top, "movers", range, (m) => fillTop(root, top, m, nav, reloadTop));
    };
    const reloadBottom = (threshold) => {
      pick.threshold = threshold;
      return reload("bottom", bottom, "mispricings_now", threshold, (m) => replace(bottom, mispricingCard(m, nav, reloadBottom)));
    };
    replace(root, head(moves.sub, null), top, bottom);
    fillTop(root, top, moves, nav, reloadTop);
    replace(bottom, mispricingCard(mis, nav, reloadBottom));
  });
}

function head(sub, seg) {
  return viewHead("Movers & outliers", sub, seg);
}

function segmented(current, onPick) {
  return el(
    "div",
    { class: "seg", attrs: { role: "group", "aria-label": "Range" } },
    RANGES.map((r) =>
      el("button", { text: r.label, attrs: { "aria-pressed": r.key === current ? "true" : "false" }, on: { click: () => r.key !== current && onPick(r.key) } }),
    ),
  );
}

function fillTop(root, top, m, nav, reload) {
  root.querySelector(".view-head")?.replaceWith(head(m.sub, segmented(m.range, reload)));
  replace(top, moverCard("Biggest risers", m.risers, nav), moverCard("Biggest fallers", m.fallers, nav));
}

function itemLink(r, nav) {
  return el("button", { class: "item-link", text: r.name, attrs: { title: `Show ${r.name} in Item detail` }, on: { click: () => nav.go("item", { item: r.id }) } });
}

function moverCard(title, card, nav) {
  const headRow = el(
    "tr",
    {},
    el("th", { text: "Item" }),
    el("th", { class: "spark-col", text: "Trend" }),
    el("th", { class: "num", text: "Lowest buyout" }),
    el("th", { class: "num", text: "Price change" }),
    el("th", { class: "num", text: "Supply change" }),
    el("th", { class: "num", text: "Sales/day" }),
  );
  const body = card.rows.length
    ? el(
        "table",
        { class: "data movers-table" },
        el("thead", {}, headRow),
        el(
          "tbody",
          {},
          card.rows.map((r) =>
            el(
              "tr",
              {},
              el("td", { class: "item-cell" }, itemLink(r, nav)),
              el("td", { class: "spark-col" }, sparkline(r.spark, r.dir)),
              el("td", { class: "num" }, coin(r.price)),
              el("td", { class: "num" }, r.change ? change(r.change.text, r.change.dir) : "–"),
              el("td", { class: "num muted", text: r.supply }),
              el("td", { class: "num", text: r.sales }),
            ),
          ),
        ),
      )
    : el("p", { class: "card-note", text: card.note ?? "Nothing to show." });
  return el(
    "section",
    { class: "card" },
    el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: title }), el("div", { class: "sub", text: card.sub }))),
    body,
  );
}

function nowMark() {
  const m = el("i", { class: "marker diamond" });
  m.style.setProperty("--marker", "var(--s4)");
  return m;
}

function mispricingCard(m, nav, reload) {
  const label = m.thresholds.find((t) => t.value === m.threshold)?.label ?? "";
  const combo = el("button", { class: "ctl threshold" }, el("span", { class: "value", text: label }), icon("chevron", 14));
  combo.addEventListener("click", () =>
    openPopover(
      combo,
      el(
        "div",
        {},
        m.thresholds.map((t) =>
          el(
            "button",
            {
              attrs: { role: "menuitemradio", "aria-checked": t.value === m.threshold ? "true" : "false" },
              on: {
                click: () => {
                  closePopover();
                  if (t.value !== m.threshold) reload(t.value);
                },
              },
            },
            t.label,
          ),
        ),
      ),
      { className: "menu" },
    ),
  );
  const key = el(
    "div",
    { class: "legend range-key" },
    el("span", {}, nowMark(), "now"),
    el("span", {}, el("i", { class: "tick" }), "usual"),
    el("span", {}, el("i", { class: "typical" }), "typical range"),
  );
  const tools = el("div", { class: "card-tools" }, key, el("span", { class: "muted small", text: "Threshold" }), combo);
  const headRow = el(
    "tr",
    {},
    el("th", { text: "Item" }),
    el("th", { class: "num", text: "Lowest buyout" }),
    el("th", { class: "num", text: m.usualLabel ?? "Usual" }),
    el("th", { class: "num", text: "Discount" }),
    el("th", { text: "Where it sits" }),
    el("th", { class: "num", text: "Qty listed" }),
    el("th", { class: "num", text: "Seen" }),
  );
  const body = m.rows.length
    ? el(
        "div",
        { class: "mispricing-scroll" },
        el(
          "table",
          { class: "data mispricing-table" },
          el("thead", {}, headRow),
          el(
            "tbody",
            {},
            m.rows.map((r) =>
              el(
                "tr",
                {},
                el("td", { class: "item-cell" }, itemLink(r, nav), el("div", { class: "sub", text: r.group })),
                el("td", { class: "num" }, coin(r.price)),
                el("td", { class: "num" }, coin(r.usual)),
                el("td", { class: "num" }, r.discount ? change(r.discount.text, r.discount.dir) : "–"),
                el("td", {}, rangeBar(r.range)),
                el("td", { class: "num", text: r.qty }),
                el("td", { class: "num", text: r.seen }),
              ),
            ),
          ),
        ),
      )
    : el("p", { class: "card-note", text: m.note ?? "Nothing to show." });
  return el(
    "section",
    { class: "card" },
    el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: "Current mispricings" }), el("div", { class: "sub", text: m.sub })), tools),
    body,
  );
}
