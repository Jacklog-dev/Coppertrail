// Market overview (HANDOVER 8b "Views", mock-ups MarketOverview, Overview1280, OverviewUltrawide).
// Data: bridge.overview() (tiles and charts) and bridge.overview_events() ("What changed",
// slower, filled in when it arrives).
import { call } from "./api.js";
import { axisCoins, axisCount, change, coin } from "./coins.js";
import { chart, chartCard, MARKERS } from "./charts.js";
import { el, replace } from "./dom.js";
import * as states from "./states.js";
import { noteCard, staleTail, tile, viewHead, viewHost } from "./viewkit.js";

const host = viewHost("overview");

const index1 = (v) => v.toFixed(1); // index tooltip values (chart formatting)

/** render(container, state, banner, nav) */
export function render(container, state, banner, nav) {
  const key = JSON.stringify([state.dataDir, state.status.lastPoint, state.filters, state.groups, state.window]);
  const head = viewHead("Market overview", state.items.sub);
  host.show(container, banner, key, head, async (root, isCurrent) => {
    const data = await call("overview");
    if (!isCurrent()) return;
    build(root, data, state, nav);
    // The slow part fails on its own: only "What changed" shows the error.
    let events;
    try {
      events = await call("overview_events");
    } catch (err) {
      events = { rows: [], note: `Could not look for events: ${err}` };
    }
    if (!isCurrent()) return;
    fillChanged(root.querySelector(".a-changed"), events, nav);
  });
}

function build(root, data, state, nav) {
  const stale = staleTail(state);
  const cards = [];
  const area = (node, name) => {
    node.classList.add("a-" + name);
    return node;
  };

  // Price index, farmable vs scarce goods
  const ix = data.index ?? {};
  let indexNode;
  if (ix.x) {
    const series = [];
    if (ix.scarce) series.push({ label: "Scarce goods", color: "s1", width: "primary", fill: true, values: ix.scarce, format: index1 });
    if (ix.farmable) series.push({ label: "Farmable goods", color: "s2", width: "secondary", values: ix.farmable, format: index1 });
    const card = chartCard({
      title: "Price index — farmable vs scarce goods",
      sub: ix.note ? `${ix.sub} · ${ix.note}` : ix.sub,
      legend: [...series, { label: "Baseline", color: "text3", dashed: true }],
      zoom: true,
      build: (p) =>
        chart(p, {
          x: ix.x,
          series,
          refLines: [{ value: 100 }],
          height: 300,
          format: (v) => Math.round(v).toString(),
          tipDate: "day",
          tipExtra: ix.divergence ? [{ label: "Divergence", values: ix.divergence, color: "text3", format: (t) => t }] : [],
          stale,
        }),
    });
    cards.push(card);
    indexNode = card.node;
  } else indexNode = noteCard("Price index — farmable vs scarce goods", ix);

  // Daily rhythm (24 h)
  const rh = data.rhythm ?? {};
  let rhythmNode;
  if (rh.hours) {
    const series = [
      { label: "Supply", color: "s2", width: "secondary", values: rh.supply },
      { label: "Lowest buyout", color: "s1", width: "primary", values: rh.price },
    ];
    const card = chartCard({
      title: "Daily rhythm",
      sub: rh.sub,
      legend: series,
      reset: false,
      build: (p) =>
        chart(p, {
          x: rh.hours,
          xHours: true,
          series,
          refLines: [{ value: 100 }],
          labels: rh.labels.map((l) => ({ ...l, color: l.series === "price" ? "s1" : "s2" })),
          height: 300,
          format: (v) => Math.round(v).toString(),
        }),
    });
    cards.push(card);
    rhythmNode = card.node;
  } else if (rh.gap) {
    rhythmNode = el(
      "section",
      { class: "card" },
      el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: "Daily rhythm" }), el("div", { class: "sub", text: rh.sub }))),
      states.needsHistory(rh.gap),
    );
    rhythmNode.querySelector(".needs-history")?.classList.add("in-card");
  } else rhythmNode = noteCard("Daily rhythm", rh);

  // Rhythm by group (ultrawide only)
  const groupsNode = rhythmGroups(rh.groups);

  // Total listed supply, total gold listed
  const supplyNode = areaCard(cards, "Total listed supply", data.supply, { label: "Listed", color: "s2", format: axisCount, value: data.supply?.value, stale, tipDate: null });
  const goldNode = areaCard(cards, "Total gold listed", data.gold, { label: "Gold listed", color: "s1", format: axisCoins, value: data.gold?.value ? coin(data.gold.value) : null, stale, tipDate: "day" });

  // What changed (filled by overview_events)
  const changed = el(
    "section",
    { class: "card changed" },
    el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: "What changed" }), el("div", { class: "sub", text: "Last 7 days" }))),
    el("div", { class: "changed-rows" }, el("p", { class: "card-note", text: "Looking for mispricings, supply shocks and buyouts…" })),
    el("button", { class: "btn link more", on: { click: () => nav.go("movers") } }, "All movers and outliers →"),
  );

  const grid = el(
    "div",
    { class: "overview-grid" },
    area(indexNode, "index"),
    area(rhythmNode, "rhythm"),
    area(groupsNode, "groups"),
    area(supplyNode, "supply"),
    area(goldNode, "gold"),
    area(changed, "changed"),
  );
  const tiles = el("div", { class: "tiles" }, (data.tiles ?? []).map(tile));
  replace(root, viewHead("Market overview", data.sub), tiles, grid);
  for (const c of cards) c.mount();
}

function areaCard(cards, title, p, { label, color, format, value, stale, tipDate }) {
  if (!p?.x) return noteCard(title, p);
  const tools = el("div", { class: "card-value" }, el("div", { class: "big" }, value), p.change ? change(p.change.text, p.change.dir) : null);
  const card = chartCard({
    title,
    sub: p.sub,
    tools,
    reset: false,
    build: (el_) => chart(el_, { x: p.x, series: [{ label, color, width: "secondary", fill: true, values: p.values }], height: 190, format, stale, tipDate }),
  });
  cards.push(card);
  return card.node;
}

function rhythmGroups(g) {
  const head = el("div", { class: "card-head" }, el("div", {}, el("h2", { class: "card-title", text: "Rhythm by group" }), el("div", { class: "sub", text: g?.sub ?? "" })));
  if (!g?.rows?.length) return el("section", { class: "card" }, head, el("p", { class: "card-note", text: g?.note ?? "Nothing to show." }));
  const rows = g.rows.map((r) => {
    const bar = el("span", { class: "bar-fill" });
    bar.style.width = `${Math.max(2, r.share * 100)}%`;
    return el(
      "div",
      { class: "group-row", attrs: { title: r.items } },
      el("span", { class: "group-name", text: r.name }),
      el("span", { class: "bar-track" }, bar),
      r.change ? change(r.change.text, r.change.dir) : el("span", { class: "muted", text: "–" }),
    );
  });
  return el("section", { class: "card" }, head, el("div", { class: "group-rows" }, rows));
}

function fillChanged(card, data, nav) {
  if (!card) return;
  card.querySelector(".sub").textContent = data.sub || "Last 7 days";
  const box = card.querySelector(".changed-rows");
  if (!data.rows?.length) {
    replace(box, el("p", { class: "card-note", text: data.note ?? "Nothing unusual in the last 7 days." }), data.failed ? el("p", { class: "card-note fall", text: data.failed }) : null);
    return;
  }
  replace(
    box,
    data.rows.map((r) => {
      const kind = MARKERS[r.kind];
      const mark = el("i", { class: "marker " + kind.shape });
      mark.style.setProperty("--marker", `var(--${kind.color})`);
      return el(
        "div",
        { class: "changed-row" },
        el("span", { class: "changed-type" }, mark, r.type),
        el(
          "div",
          { class: "changed-item" },
          el("button", { class: "item-link", text: r.name, attrs: { title: `Show ${r.name} in Item detail` }, on: { click: () => nav.go("item", { item: r.id }) } }),
          el("div", { class: "sub", text: `${r.detail} · ${r.when}` }),
        ),
      );
    }),
    data.failed ? el("p", { class: "card-note fall", text: data.failed }) : null,
  );
}
