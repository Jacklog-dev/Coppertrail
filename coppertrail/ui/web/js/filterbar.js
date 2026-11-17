// Filter bar (HANDOVER 8b): Groups (+ edit), Class, Search, date range, Min sales/day,
// then the active-filter count and Reset. Every change goes to the bridge (`set_filters`),
// which saves it and returns the new state; the whole frame re-renders from that.
//
// Re-rendering replaces the bar's DOM, so this module remembers which popover is open and
// which field had focus, and restores both after each render.
import { call } from "./api.js";
import { calendar, dayLabel } from "./calendar.js";
import { el, replace } from "./dom.js";
import { openGroupEditor } from "./groupeditor.js";
import { icon } from "./icons.js";
import { closePopover, openPopover } from "./popover.js";

const RANGES = [
  ["24h", "24 h"],
  ["7d", "7 d"],
  ["30d", "30 d"],
  ["all", "All"],
];
const MIN_SALES_PRESETS = [0, 10, 50, 200, 1000];
const SEARCH_DELAY_MS = 250;

const ui = {
  open: null, // "groups" | "class" | "date" | "sales" | "more"
  groupSearch: "",
  month: null, // "YYYY-MM" shown in the calendar
  pending: null, // first calendar click
  searchText: null, // typed but not saved yet: wins over state.filters.search
};
let ctx = null; // {container, state, onState}
let searchTimer = null;

// Filter changes go to the bridge one at a time, in order, so the saved filters are always
// the last ones sent; only the newest response is rendered.
let queue = Promise.resolve();
let sent = 0;
function send(name, ...args) {
  const mine = ++sent;
  const reply = queue.then(() => call(name, ...args));
  queue = reply.catch(() => {});
  return reply.then((next) => {
    if (mine === sent) ctx.onState(next);
  });
}

const change = (partial) => send("set_filters", partial);

/** Change filters from outside the bar (no-match chips): same ordered queue as the bar. */
export function setFilters(partial) {
  return change(partial);
}

/** "Reset all filters" from outside the bar: also drops typed-but-unsaved search text. */
export function resetFilters() {
  return reset();
}

function reset() {
  ui.open = null;
  ui.searchText = null;
  clearTimeout(searchTimer);
  searchTimer = null;
  closePopover(false);
  return send("reset_filters");
}

function editGroups(newGroup = false) {
  ui.open = null;
  closePopover(false);
  openGroupEditor(ctx.state, { newGroup, onState: ctx.onState });
}

function toggle(kind, anchor) {
  if (ui.open === kind) {
    ui.open = null;
    closePopover(false);
    return;
  }
  ui.open = kind;
  ui.pending = null;
  if (kind === "date") ui.month = ctx.state.window.to.slice(0, 7);
  showPopover(anchor);
}

/**
 * The element a popover hangs from. In a compact window (<= 1440 px) Class, date and Min
 * sales are folded into "More" and hidden, so their popovers open under "More" instead.
 */
function anchorFor(kind) {
  const own = ctx.container.querySelector(`[data-anchor="${kind}"]`);
  if (own && own.getClientRects().length) return own;
  return ctx.container.querySelector('[data-anchor="more"]');
}

function showPopover(anchor) {
  const build = { groups: groupsPopover, class: classMenu, date: datePopover, sales: salesPopover, more: morePopover }[ui.open];
  if (!build || !anchor) return;
  const [content, className] = build();
  openPopover(anchor, content, { className, onClose: () => (ui.open = null) });
}

// Popovers ------------------------------------------------------------------------

function groupsPopover() {
  const s = ctx.state;
  const selected = new Set(s.filters.groups);
  const needle = ui.groupSearch.trim().toLowerCase();
  const rows = s.groups
    .filter((g) => !needle || g.name.toLowerCase().includes(needle))
    .map((g) => {
      const on = selected.has(g.name);
      const box = el("span", { class: "check", attrs: { "aria-checked": on ? "true" : "false" } }, on ? icon("check", 12) : null);
      return el(
        "button",
        {
          class: "pop-row",
          attrs: { role: "menuitemcheckbox", "aria-checked": on ? "true" : "false" },
          on: {
            click: () => {
              const next = on ? s.filters.groups.filter((n) => n !== g.name) : s.groups.map((x) => x.name).filter((n) => n === g.name || selected.has(n));
              change({ groups: next });
            },
          },
        },
        box,
        el("span", { class: "name", text: g.name }),
        el("span", { class: "count", text: `${g.count.toLocaleString("en-US")} ${g.count === 1 ? "item" : "items"}` }),
      );
    });
  const search = el("input", {
    attrs: { placeholder: "Search groups", value: ui.groupSearch, "data-focus": "group-search" },
    on: {
      input: (e) => {
        ui.groupSearch = e.target.value;
        showPopover(anchorFor("groups"));
        refocus("group-search");
      },
    },
  });
  const content = el(
    "div",
    {},
    el("div", { class: "pop-search" }, el("label", { class: "input" }, icon("search", 16), search)),
    el(
      "div",
      { class: "pop-summary" },
      el("span", { text: s.groupsSummary }),
      el(
        "span",
        {},
        el("button", { class: "btn link", text: "All", on: { click: () => change({ groups: s.groups.map((g) => g.name) }) } }),
        el("button", { class: "btn link", text: "None", on: { click: () => change({ groups: [] }) } }),
      ),
    ),
    el("div", { class: "rows", attrs: { role: "menu" } }, rows.length ? rows : el("div", { class: "pop-row muted", text: "No group matches" })),
    el(
      "div",
      { class: "pop-foot" },
      el("button", { class: "btn link", on: { click: () => editGroups(true) } }, icon("plus", 14), "New group"),
      el("button", { class: "btn link", on: { click: () => editGroups(false) } }, icon("edit", 14), "Edit groups…"),
    ),
  );
  return [content, "popover pop-groups"];
}

function classMenu() {
  const s = ctx.state;
  const options = [["", "All classes"], ...s.classes.map((c) => [c, c])];
  const content = el(
    "div",
    { attrs: { role: "menu" } },
    options.map(([value, label]) =>
      el("button", {
        text: label,
        attrs: { role: "menuitemradio", "aria-checked": s.filters.item_class === value ? "true" : "false" },
        on: {
          click: () => {
            ui.open = null;
            closePopover(false);
            change({ item_class: value });
          },
        },
      }),
    ),
  );
  return [content, "menu"];
}

function rangeSeg() {
  const current = ctx.state.filters.range;
  return el(
    "div",
    { class: "seg", attrs: { role: "group", "aria-label": "Date range" } },
    RANGES.map(([value, label]) =>
      el("button", {
        text: label,
        attrs: { "aria-pressed": current === value ? "true" : "false" },
        on: { click: () => change({ range: value }) },
      }),
    ),
  );
}

function datePopover() {
  const s = ctx.state;
  const w = s.window;
  const field = (label, iso) => el("label", {}, label, el("span", { class: "input", text: dayLabel(iso) }));
  const note = w.archiveFrom
    ? `Archive: ${dayLabel(w.archiveFrom)} – ${dayLabel(w.archiveTo)}. Click two days for a custom range.`
    : "No data in the archive yet.";
  const content = el(
    "div",
    {},
    rangeSeg(),
    el("div", { class: "fromto" }, field("From", ui.pending ?? w.from), field("To", ui.pending ? null : w.to)),
    calendar({
      from: w.from,
      to: w.to,
      min: w.archiveFrom,
      max: w.archiveTo,
      month: ui.month,
      pending: ui.pending,
      onMonth: (ym) => {
        ui.month = ym;
        showPopover(anchorFor("date"));
      },
      onDay: (day) => {
        if (!ui.pending) {
          ui.pending = day;
          showPopover(anchorFor("date"));
          return;
        }
        const [lo, hi] = [ui.pending, day].sort();
        ui.pending = null;
        change({ range: "custom", date_from: lo, date_to: hi });
      },
    }),
    el("div", { class: "note", text: note }),
  );
  content.style.display = "contents";
  return [content, "popover pop-date"];
}

function salesPopover() {
  const s = ctx.state;
  const content = el(
    "div",
    {},
    el("div", { class: "label", text: "Minimum sales per day" }),
    el(
      "div",
      { class: "chips" },
      MIN_SALES_PRESETS.map((n) =>
        el("button", {
          class: "chip",
          text: n.toLocaleString("en-US"),
          attrs: { "aria-pressed": s.filters.min_sales === n ? "true" : "false" },
          on: { click: () => change({ min_sales: n }) },
        }),
      ),
    ),
    el("div", { class: "note", text: s.minSalesPass }),
  );
  content.style.display = "contents";
  return [content, "popover pop-sales"];
}

// Controls that fold into "More" in a compact window -------------------------------------

const FOLDED = ["Class", "Date range", "Min sales/day"]; // labels as in state.active

function classCtl(on) {
  return el(
    "button",
    { class: "ctl" + on("Class"), attrs: { "data-anchor": "class", "aria-haspopup": "menu" }, on: { click: () => toggle("class", anchorFor("class")) } },
    el("span", { class: "label", text: "Class" }),
    el("span", { class: "value", text: ctx.state.filters.item_class || "All classes" }),
    el("span", { class: "chev" }, icon("chevron", 14)),
  );
}

function dateCtl(on) {
  return el(
    "button",
    { class: "ctl" + on("Date range"), attrs: { "data-anchor": "date", "aria-haspopup": "dialog" }, on: { click: () => toggle("date", anchorFor("date")) } },
    icon("calendar", 16),
    el("span", { class: "value", text: ctx.state.window.label }),
  );
}

function salesCtl(on, focusKey) {
  const input = el("input", {
    attrs: { type: "number", min: 0, step: 10, value: ctx.state.filters.min_sales, "data-focus": focusKey, "aria-label": "Minimum sales per day" },
    on: {
      change: (e) => change({ min_sales: Math.max(0, parseInt(e.target.value, 10) || 0) }),
      click: (e) => e.stopPropagation(),
    },
  });
  return el(
    "div",
    { class: "ctl minsales" + on("Min sales/day"), attrs: { "data-anchor": "sales", role: "group" }, on: { click: () => toggle("sales", anchorFor("sales")) } },
    el("span", { class: "label", text: "Min sales/day" }),
    input,
  );
}

/** "More" (compact window): the three folded controls; each opens its own popover here. */
function morePopover() {
  const active = new Set(ctx.state.active);
  const on = (name) => (active.has(name) ? " active" : "");
  const content = el("div", {}, classCtl(on), dateCtl(on), salesCtl(on, "min-sales-more"));
  content.style.display = "contents";
  return [content, "popover pop-more"];
}

// Focus keeping ---------------------------------------------------------------------

function refocus(key, caret) {
  const node = document.querySelector(`[data-focus="${key}"]`);
  if (!node) return;
  node.focus();
  const pos = caret ?? node.value?.length ?? 0;
  if (node.setSelectionRange && node.type !== "number") node.setSelectionRange(pos, pos);
}

// Render ------------------------------------------------------------------------------

/** render(container, state, onState) — onState(newState) re-renders the whole frame. */
export function render(container, state, onState) {
  const focused = document.activeElement?.dataset?.focus;
  const caret = document.activeElement?.selectionStart;
  ctx = { container, state, onState };
  const f = state.filters;
  const active = new Set(state.active);
  const on = (name) => (active.has(name) ? " active" : "");

  const groups = el(
    "button",
    { class: "ctl groups" + on("Groups"), attrs: { "data-anchor": "groups", "aria-haspopup": "dialog" }, on: { click: (e) => toggle("groups", e.currentTarget) } },
    el("span", { class: "label", text: "Groups" }),
    el("span", { class: "value", text: state.groupsLabel }),
    el("span", { class: "chev" }, icon("chevron", 14)),
  );
  const pencil = el("button", { class: "ctl", attrs: { "aria-label": "Edit item groups", title: "Edit item groups" }, on: { click: () => editGroups(false) } }, icon("edit", 16));
  pencil.style.padding = "0 8px";


  const searchInput = el("input", {
    attrs: { type: "search", placeholder: "Search items", value: ui.searchText ?? f.search, "data-focus": "search", "aria-label": "Search items" },
    on: {
      input: (e) => {
        clearTimeout(searchTimer);
        const text = e.target.value;
        ui.searchText = text; // re-renders before the save keep what was typed
        searchTimer = setTimeout(async () => {
          searchTimer = null;
          await change({ search: text });
          if (searchTimer === null && ui.searchText === text) ui.searchText = null;
        }, SEARCH_DELAY_MS);
      },
    },
  });
  const search = el("label", { class: "input search" + on("Search") }, icon("search", 16), searchInput);

  const folded = FOLDED.filter((name) => active.has(name)).length;
  const more = el(
    "button",
    {
      class: "ctl more" + (folded ? " active" : ""),
      attrs: { "data-anchor": "more", "aria-haspopup": "dialog", "aria-label": folded ? `More filters, ${folded} active` : "More filters" },
      on: { click: (e) => toggle("more", e.currentTarget) },
    },
    icon("sliders", 15),
    el("span", { text: "More" }),
    folded ? el("span", { class: "badge", text: String(folded) }) : null,
  );

  const activeState = state.active.length
    ? el(
        "div",
        { class: "active-state" },
        el("span", { class: "active-label" }, el("span", { class: "dot accent" }), state.activeLabel),
        el("button", { class: "btn ghost", on: { click: reset } }, icon("reset", 14), "Reset"),
      )
    : el("div", { class: "active-state" }, el("span", { class: "no-filters", text: "No filters" }));

  replace(
    container,
    el("div", { class: "group-pair" }, groups, pencil),
    el("div", { class: "fold" }, classCtl(on)),
    search,
    el("div", { class: "group-pair" }, rangeSeg(), el("div", { class: "fold" }, dateCtl(on))),
    el("div", { class: "fold" }, salesCtl(on, "min-sales")),
    more,
    el("div", { class: "spacer" }),
    activeState,
  );

  if (ui.open) showPopover(anchorFor(ui.open));
  if (focused) refocus(focused, caret);
}
